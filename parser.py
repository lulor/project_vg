
import argparse


def parse_arguments():
    parser = argparse.ArgumentParser(description="Benchmarking Visual Geolocalization",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    # Training parameters
    parser.add_argument("--train_batch_size", type=int, default=4,
                        help="Number of triplets (query, pos, negs) in a batch. Each triplet consists of 12 images")
    parser.add_argument("--infer_batch_size", type=int, default=16,
                        help="Batch size for inference (caching and testing)")
    parser.add_argument("--margin", type=float, default=0.1,
                        help="margin for the triplet loss")
    parser.add_argument("--epochs_num", type=int, default=50,
                        help="Maximum number of epochs to train for")
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--lr", type=float, default=1e-05, help="Learning rate")
    parser.add_argument("--cache_refresh_rate", type=int, default=1000,
                        help="How often to refresh cache, in number of queries")
    parser.add_argument("--queries_per_epoch", type=int, default=5000,
                        help="How many queries to consider for one epoch. Must be multiple of cache_refresh_rate")
    parser.add_argument("--negs_num_per_query", type=int, default=10,
                        help="How many negatives to consider per each query in the loss")
    parser.add_argument("--neg_samples_num", type=int, default=1000,
                        help="How many negatives to use to compute the hardest ones")
    # Other parameters
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--num_workers", type=int, default=8, help="num_workers for all dataloaders")
    parser.add_argument("--val_positive_dist_threshold", type=int, default=25, help="Val/test threshold in meters")
    parser.add_argument("--train_positives_dist_threshold", type=int, default=10, help="Train threshold in meters")
    parser.add_argument("--recall_values", type=int, default=[1, 5, 10, 20], nargs="+",
                        help="Recalls to be computed, such as R@5.")
    parser.add_argument("--augment", type=str, default=None,choices=["color_jitter"],
                        help="The augmentation to use on training set")
    # Paths parameters
    parser.add_argument("--datasets_folder", type=str, required=True, help="Path with datasets")
    parser.add_argument("--exp_name", type=str, default="default",
                        help="Folder name of the current run (saved in ./runs/)")
    parser.add_argument("--resume", type=str, help="The model to resume")

    parser.add_argument("--optim", type=str, default="adam", choices=["adam", "sgd"],
                        help="The optimizer to use")
    parser.add_argument("--mode", type=str, default="avg_pool", choices=["avg_pool", "netvlad", "gem"],
                        help="The aggregation mode to use")
    parser.add_argument("--test_only", type=bool, default=False,
                        help="Whether the model should be trained or not")
    parser.add_argument("--loss", type=str, default="triplet",
                        choices=["triplet", "sare_joint", "sare_ind"],
                        help="The loss to use")
    parser.add_argument("--sos", type=bool, default=False,
                        help="whether to use sos loss")
    parser.add_argument("--sos_lambda", type=float, default=5,
                        help="the lambda param for sos loss")
    parser.add_argument("--attention", type=str, default=None, choices=["cbam", "crn"],
                        help="The attention mode to use (CBAM or CRN), if any")
    parser.add_argument("--crn_lr_mult", type=int, default=10,
                        help="Multiplier of the lr to use for the CRN")
    parser.add_argument("--ds", type=str, default="pitts30k", choices=["pitts30k", "st_lucia"],
                        help="The dataset to use")

    # NetVLAD only
    parser.add_argument("--num_clusters", type=int, default=64,
                        help="How many clusters to use for NetVLAD")

    args = parser.parse_args()

    if args.queries_per_epoch % args.cache_refresh_rate != 0:
        raise ValueError("Ensure that queries_per_epoch is divisible by cache_refresh_rate, " +
                         f"because {args.queries_per_epoch} is not divisible by {args.cache_refresh_rate}")
    return args
