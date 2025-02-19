
import math
import torch
import logging
import numpy as np
from tqdm import tqdm
import torch.nn as nn
import multiprocessing
from os.path import join
from datetime import datetime
from torch.utils.data.dataloader import DataLoader
torch.backends.cudnn.benchmark= True  # Provides a speedup

import util
import test
import parser
import commons
import network
import datasets_ws
import sare_loss

#### Initial setup: parser, logging...
args = parser.parse_arguments()

if args.resume is None:
    if args.test_only: raise RuntimeError("No model specified for testing")
    checkpoint = None
else:
    checkpoint = util.load_state(args.resume)
    args = util.load_args_from_state(checkpoint, args)

start_time = datetime.now()
args.output_folder = join("runs", args.exp_name, start_time.strftime('%Y-%m-%d_%H-%M-%S'))
commons.setup_logging(args.output_folder)
commons.make_deterministic(args.seed)
if checkpoint is not None:
    logging.debug(f"Arguments loaded from checkpoint '{args.resume}'")
logging.info(f"Arguments: {args}")
logging.info(f"The outputs are being saved in {args.output_folder}")
logging.info(f"Using {torch.cuda.device_count()} GPUs and {multiprocessing.cpu_count()} CPUs")

#### Creation of Datasets
logging.debug(f"Loading dataset Pitts30k from folder {args.datasets_folder}")

if not args.test_only:
    triplets_ds = datasets_ws.TripletsDataset(args, args.datasets_folder, args.ds, "train", args.negs_num_per_query)
    logging.info(f"Train query set: {triplets_ds}")

    val_ds = datasets_ws.BaseDataset(args, args.datasets_folder, args.ds, "val")
    logging.info(f"Val set: {val_ds}")

test_ds = datasets_ws.BaseDataset(args, args.datasets_folder, args.ds, "test")
logging.info(f"Test set: {test_ds}")

#### Initialize model
if args.resume is None and args.mode == "netvlad":
    args.cluster_ds = datasets_ws.BaseDataset(args, args.datasets_folder, args.ds, "train")
model = network.GeoLocalizationNet(args)
model = model.to(args.device)

#### Setup Optimizer and Loss
optimizer, scheduler = util.get_optimizer(args, model)
criterion, criterion_sos = util.get_loss(args)

#### Eventual model resuming
if checkpoint is None:
    last_epoch_num = 0
    best_r5 = 0
    not_improved_num = 0
else:
    last_epoch_num, recalls, best_r5, not_improved_num = util.resume_from_state(checkpoint, model, optimizer, scheduler)
    best_r5 = max(best_r5, recalls[1])
    logging.debug(f"Successfully loaded model from checkpoint (epoch: {last_epoch_num}, recalls: {recalls})")
del checkpoint


logging.info(f"Output dimension of the model is {args.features_dim}")

if not args.test_only:

    #### Training loop
    for epoch_num in range(last_epoch_num + 1, args.epochs_num + 1):

        if scheduler is not None:
            scheduler.step(epoch_num)

        logging.info(f"Start training epoch: {epoch_num:02d}")

        epoch_start_time = datetime.now()
        epoch_losses = np.zeros((0,1), dtype=np.float32)

        # How many loops should an epoch last (default is 5000/1000=5)
        loops_num = math.ceil(args.queries_per_epoch / args.cache_refresh_rate)
        for loop_num in range(1, loops_num + 1):
            logging.debug(f"Cache: {loop_num} / {loops_num}")

            # Compute triplets to use in the triplet loss
            triplets_ds.is_inference = True
            triplets_ds.compute_triplets(args, model)
            triplets_ds.is_inference = False

            triplets_dl = DataLoader(dataset=triplets_ds, num_workers=args.num_workers,
                                     batch_size=args.train_batch_size,
                                     collate_fn=datasets_ws.collate_fn,
                                     pin_memory=(args.device=="cuda"),
                                     drop_last=True)

            model = model.train()

            # images shape: (train_batch_size*12)*3*H*W ; by default train_batch_size=4, H=480, W=640
            # triplets_local_indexes shape: (train_batch_size*10)*3 ; because 10 triplets per query
            

            for images, triplets_local_indexes, _ in tqdm(triplets_dl, ncols=100):

                # Compute features of all images (images contains queries, positives and negatives)
                features = model(images.to(args.device))
                loss = 0
                
                triplets_local_indexes = torch.transpose(
                    triplets_local_indexes.view(args.train_batch_size, args.negs_num_per_query, 3), 1, 0)
                for triplets in triplets_local_indexes:
                    queries_indexes, positives_indexes, negatives_indexes = triplets.T
                    if args.loss == "triplet":
                        loss += criterion(features[queries_indexes],
                                          features[positives_indexes],
                                          features[negatives_indexes])
                    else:
                        output_features = torch.Tensor().to(args.device)
                        # queries_indexes,positive_indexes and negative_indexes have the same length
                        for x in range(len(queries_indexes)):
                            # get query, pos and neg index
                            q = queries_indexes[x]
                            p = positives_indexes[x]
                            n = negatives_indexes[x]
                            # get corresponding features
                            query = features[q]
                            positive = features[p]
                            negative = features[n]
                            # update input tensor for sare_loss
                            output_features = torch.cat((output_features, query, positive, negative))
                        # loss
                        loss += sare_loss.get_loss(output_features, args.loss, args.train_batch_size, 3)

                del features
                loss /= (args.train_batch_size * args.negs_num_per_query)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                # Keep track of all losses by appending them to epoch_losses
                batch_loss = loss.item()
                epoch_losses = np.append(epoch_losses, batch_loss)
                del loss

            logging.debug(f"Epoch[{epoch_num:02d}]({loop_num}/{loops_num}): " +
                          f"current batch triplet loss = {batch_loss:.4f}, " +
                          f"average epoch triplet loss = {epoch_losses.mean():.4f}")

        logging.info(f"Finished epoch {epoch_num:02d} in {str(datetime.now() - epoch_start_time)[:-7]}, "
                     f"average epoch triplet loss = {epoch_losses.mean():.4f}")

        # Compute recalls on validation set
        recalls, recalls_str = test.test(args, val_ds, model)
        logging.info(f"Recalls on val set {val_ds}: {recalls_str}")

        is_best = recalls[1] > best_r5

        if is_best:
            logging.info(f"Improved: previous best R@5 = {best_r5:.1f}, current R@5 = {recalls[1]:.1f}")
            best_r5 = recalls[1]
            not_improved_num = 0
        else:
            not_improved_num += 1
            logging.info(f"Not improved: {not_improved_num} / {args.patience}: best R@5 = {best_r5:.1f}, current R@5 = {recalls[1]:.1f}")

        # Save checkpoint, which contains all training parameters
        state = util.make_state(args, epoch_num, model, optimizer, scheduler, recalls, best_r5, not_improved_num)
        util.save_checkpoint(args, state, is_best, filename=f"model_{epoch_num:02d}.pth")

        # If recall@5 did not improve for "many" epochs, stop training
        if not_improved_num >= args.patience:
            logging.info(f"Performance did not improve for {not_improved_num} epochs. Stop training.")
            break

    logging.info(f"Best R@5: {best_r5:.1f}")
    logging.info(f"Trained for {epoch_num:02d} epochs, in total in {str(datetime.now() - start_time)[:-7]}")

#### Test best model on test set
# best_model_state_dict = torch.load(join(args.output_folder, "best_model.pth"))["model_state_dict"]
# model.load_state_dict(best_model_state_dict)

recalls, recalls_str = test.test(args, test_ds, model)
logging.info(f"Recalls on {test_ds}: {recalls_str}")
