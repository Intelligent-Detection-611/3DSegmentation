from Data.prepare_dataloader import get_from_loader_segthor, get_from_loader_brats
import torch
import torch.optim as optim
from axial_fusion_transformer import axial_fusion_transformer
import os
from tqdm import tqdm 
from operator import add
import yaml 
import json
from check_size_and_voxels.check_dataset import check_dataset
import wandb
from monai.losses import DiceLoss
from monai.metrics import DiceMetric, MeanIoU
import warnings
from utils import visualize_img_mask_output
from monai.transforms import AsDiscrete, Compose, Activations

import numpy as np
import argparse
from monai.networks.nets import UNet
from monai.networks.layers import Norm
# CUDA_VISIBLE_DEVICES=1 python3 train.py config/train_config.yaml --model unet --dataset_to_use segthor_data --checkpoint model_unet.pth
# or model that can be used axial_fusion_transformer

# CUDA_VISIBLE_DEVICES=1 python3 train.py config/train_config.yaml --model unet --dataset_to_use segthor_data --checkpoint model_unet_improved.pth

# CUDA_VISIBLE_DEVICES=1 python3 train.py config/train_config.yaml --model axial_fusion_transformer --dataset_to_use segthor_data --checkpoint model_axial.pth

with open('./config/train_config.yaml', 'r') as config_file:
    config_params = yaml.safe_load(config_file)
    model_config = json.dumps(config_params)

def training_phase(train_dataloader, test_dataloader, num_classes,num_channels_before_training, args):

    num_epochs = wandb.config['epochs']

    Na = config_params["training_params"]["Na"]
    Nf = config_params["training_params"]["Nf"]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if args.model == "axial_fusion_transformer":
        model = axial_fusion_transformer(Na,Nf, num_classes,num_channels_before_training).to(device)
    elif args.model == 'unet':
        model = UNet(
            spatial_dims=3,
            in_channels = num_channels_before_training,
            channels = (8,16,32,64,128),
            out_channels=num_classes,
            strides=(2, 2, 2, 2),
            norm=Norm.BATCH).to(device)


    loss_function = DiceLoss(include_background=True, reduction="mean")

    dice_metric = DiceMetric(include_background=True, reduction="mean")
    iou_metric = MeanIoU()

    optimizer = optim.AdamW(model.parameters(), lr = wandb.config['lr'],weight_decay=0.0001,betas=(0.9, 0.99))

    start_epoch = 1

    if args.checkpoint is not None:
        if os.path.exists(args.checkpoint):
            checkpoint = torch.load(args.checkpoint)
            model.load_state_dict(checkpoint['model_state_dict'])
            optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
            start_epoch = checkpoint['epoch'] + 1
            print(f"Resuming training from epoch {start_epoch}")
    
    # lr scheduler helps in stopping overfitting
    lr_scheduler = torch.optim.lr_scheduler.LinearLR(optimizer, start_factor=1.0, end_factor=0.5, total_iters=30)


    for epoch in range(start_epoch,num_epochs+1):
        images_wandb_train = []
        images_wandb_test = []
        train_loss_epoch, test_loss_epoch = [],[]
        model.train()
        for count, img_and_mask in enumerate(tqdm(train_dataloader, desc=f'Training Epoch {epoch}/{num_epochs}', unit='epoch')):
            image, mask = (img_and_mask["image"].to(device), img_and_mask["label"].to(device))

            optimizer.zero_grad()
            output = model(image)

            if args.model == "axial_fusion_transformer":
                output = output.unsqueeze(dim=0) # BECAUSE OUR MODEL ONLY WORKS FOR 1 BATCH SIZE AND WANT TO MAKE IT TO MORE BATCH SIZE SO.........

            output = Activations(softmax=True, dim=1)(output) # Adding softmax before passing to loss function

            # print(image.shape) # torch.Size([1, 1, 128, 128, 128])
            # print(mask.shape) # torch.Size([1, 5, 128, 128, 128])
            # print(mask.unique()) # tensor([0., 1.], device='cuda:0')
            # print(output.shape) # torch.Size([1, 5, 128, 128, 128])

            # print(output.max()) # tensor(0.9105, device='cuda:0', grad_fn=<AliasBackward0>)
            # print(output.min()) # tensor(0.0061, device='cuda:0', grad_fn=<AliasBackward0>)

            train_loss = loss_function(mask,output) # DICE LOSS TAKES I/P in the form of Batch Channel HWD 
            train_loss.backward()
            
            #Adding AsDiscrete before passing to DiceMetric
            output = AsDiscrete(threshold=0.5)(output) 

            # print(output.shape) #torch.Size([1, 5, 128, 128, 128])
            # print(mask.shape) #torch.Size([1, 5, 128, 128, 128])
            # print(output.unique()) # metatensor([0., 1.], device='cuda:0')
            # print(mask.unique()) # metatensor([0., 1.], device='cuda:0')
            
            dice_metric(output, mask) # DICE METRIC TAKES I/P in the form of Batch Channel HWD 
            iou_metric(output, mask) # MEAN IOU TAKES I/P in the form of Batch Channel HWD

            wandb.log({"train_loss":train_loss.item()})
            # print(train_loss)
            train_loss_epoch.append(train_loss.detach().cpu())
            # print(computed_dice_train)
            # print(computed_iou_train)
            
            optimizer.step()

            # FOR LOGGIN THE IMAGES IN THE WANDB AND VISUALIZING RESULTS
            if count%10 ==0:
                train_img_list = visualize_img_mask_output(image, mask, output, num_channels_before_training)
                images_wandb_train.extend(train_img_list)

        lr_scheduler.step()

        dice_score_train = dice_metric.aggregate().item()
        jaccard_score_train = iou_metric.aggregate().item()


        # print(f'Dice Score Train : {type(dice_score_train)}') # Dice Score Train : <class 'float'>
        # print(f'Jaccard Score Train : {type(jaccard_score_train)}') # Jaccard Score Train : <class 'float'>
        # print(f'Train Loss : {type(train_loss)}') # Train Loss : <class 'monai.data.meta_tensor.MetaTensor'>

        dice_metric.reset()
        iou_metric.reset()
        
        model.eval()
        with torch.no_grad():
            for count, img_and_mask in enumerate(tqdm(test_dataloader, desc=f'Test Epoch {epoch}/{num_epochs}', unit='epoch')):
                torch.cuda.empty_cache()
                image, mask = (img_and_mask["image"].to(device), img_and_mask["label"].to(device))

                # print(image.shape) # torch.Size([1, 1, 128, 128, 128])
                # print(mask.shape) # torch.Size([1, 5, 128, 128, 128])

                output = model(image)

                if args.model == "axial_fusion_transformer":
                    output = output.unsqueeze(dim=0)

                output = Activations(softmax=True, dim=1)(output) # Adding softmax before passing to loss function
                
                test_loss = loss_function(mask,output) # DICE LOSS TAKES I/P in the form of Batch Channel HWD 

                # print(dice_score_test) # metatensor([[0.9115]])
                # print(output.shape) # torch.Size([5, 128, 128, 128])
                # print(mask.shape) # torch.Size([1, 5, 128, 128, 128])

                # THe transforms should be always after calculating loss becoz it might be not differenciable

                #Adding AsDiscrete before passing to DiceMetric
                output = AsDiscrete(threshold=0.5)(output) 

                dice_metric(output, mask) # DICE METRIC TAKES I/P in the form of Batch Channel HWD
                iou_metric(output, mask) # MEAN IOU TAKES I/P in the form of Batch Channel HWD

                wandb.log({"test_loss":test_loss.item()})
                # print(test_loss)
                test_loss_epoch.append(test_loss.detach().cpu())

                # print(computed_dice_test)
                # print(computed_iou_test)


                # FOR LOGGIN THE IMAGES IN THE WANDB AND VISUALIZING RESULTS
                if count%10 ==0:
                    test_img_list = visualize_img_mask_output(image, mask, output, num_channels_before_training)
                    images_wandb_test.extend(test_img_list)
                
            dice_score_test = dice_metric.aggregate().item()
            jaccard_score_test = iou_metric.aggregate().item()

            # print(dice_score_test.shape) #torch.Size([1, 5])
            # print(jaccard_score_test_monai.shape) #torch.Size([1, 5])

            dice_metric.reset()
            iou_metric.reset()

                
        torch.save({'epoch':epoch, 
                    'model_state_dict':model.state_dict(),
                    'optimizer_state_dict':optimizer.state_dict(),
                    }, args.checkpoint)
        
        # print(type(train_loss)) # <class 'monai.data.meta_tensor.MetaTensor'>
        # print(type(test_loss)) # <class 'monai.data.meta_tensor.MetaTensor'>

        # print(type(dice_score_train)) # <class 'float'>
        # print(type(dice_score_test)) # <class 'float'>

        # print(type(computed_dice_train)) # <class 'monai.data.meta_tensor.MetaTensor'>
        # print(type(computed_dice_test)) # <class 'monai.data.meta_tensor.MetaTensor'>
        # print(type(computed_iou_train)) # <class 'monai.data.meta_tensor.MetaTensor'>
        # print(type(computed_iou_test)) # <class 'monai.data.meta_tensor.MetaTensor'>

        # print(type(dice_score_train_2)) # <class 'float'>
        # print(type(dice_score_test_2)) # <class 'float'>
        # print(type(jaccard_score_train)) # <class 'float'>
        # print(type(jaccard_score_test)) # <class 'float'>

        wandb.log({
                    "train_dice":dice_score_train,
                   "test_dice":dice_score_test, 

                   "train_jaccard":jaccard_score_train,
                   "test_jaccard":jaccard_score_test,

                   "image_wandb_train": [wandb.Image(img) for img in images_wandb_train],
                   "image_wandb_test": [wandb.Image(img) for img in images_wandb_test]})    
        
        print(f'Epoch [{epoch}/{num_epochs}], '
            f'Train Loss: {np.array(train_loss_epoch).mean():.4f}, '
            f'Test Loss: {np.array(test_loss_epoch).mean():.4f}, '

            f'Train Dice Score: {dice_score_train:.4f}, '
            f'Test Dice Score: {dice_score_test:.4f}, '

            f'Train Jaccard: {jaccard_score_train:.4f}, '
            f'Test Jaccard: {jaccard_score_test:.4f}, '
            )
    
    return model,num_epochs,optimizer, train_loss


# def parse_training_arguments():
#     parser = argparse.ArgumentParser()
#     parser.add_argument("train_config")
#     # parser.add_argument("val_config")
#     parser.add_argument("--model")
#     parser.add_argument("--dataset_to_use")
#     parser.add_argument('--checkpoint')
#     args = parser.parse_args()
#     return args

# CUDA_VISIBLE_DEVICES=1 python3 train.py config/train_config.yaml --model axial_fusion_transformer --dataset_to_use segthor_data --checkpoint model_axial.pth
def parse_training_arguments():
    parser = argparse.ArgumentParser()
    # 位置参数 train_config 仍然是必需的，没有默认值

    parser.add_argument("--train_config",
                        default=r"D:\task\github\AFTer-UNet-Architecture-main\config\train_config.yaml",
                        help="Path to the training configuration file (e.g., .yaml).")
    parser.add_argument("--model",
                        default="axial_fusion_transformer",
                        help="Name or type of the model to use for training.")
    parser.add_argument("--dataset_to_use",
                        default="segthor_data",
                        help="Name of the dataset to be used for training.")
    parser.add_argument('--checkpoint',
                        default=None, # 如果不提供 --checkpoint，则默认为 None
                        help="Path to a pre-trained model checkpoint or for resuming training.")
    args = parser.parse_args()
    return args # 返回解析后的参数


if __name__ =='__main__':

    warnings.filterwarnings("ignore")

    wandb.login(key=config_params["training_params"]["wandb_key"])

    wandb.init(
        mode="disabled",
        project="SegTHOR New Axial Implementation",
        config={
            "epochs": config_params["training_params"]["num_epochs"],
            "batch_size": config_params["training_params"]["batch_size"],
            "lr": config_params["training_params"]["lr"]
        }
    )

    args = parse_training_arguments()

    print(args)
    
    train_config = args.train_config
    # val_config = args.val_config
    dataset_to_use = args.dataset_to_use

    # print(num_classes) #5
    batch_size = wandb.config['batch_size']
    if dataset_to_use == "segthor_data":
        image_location = r'D:\task\github\AFTer-UNet-Architecture-main\Data\segthorDataset\train/P*/P*.nii.gz'
        mask_location = r'D:\task\github\AFTer-UNet-Architecture-main\Data\segthorDataset\train/P*/G*.nii.gz'
        
        num_classes = 5
        num_channels_before_training = 1
        
        train_dataloader, test_dataloader, _,_ = get_from_loader_segthor(image_location, mask_location, batch_size,num_classes)

    elif dataset_to_use =="brats_data":
        t2_location = '/mnt/Enterprise2/shirshak/BraTS2020_TrainingData/MICCAI_BraTS2020_TrainingData/*/*t2.nii'
        t1ce_location = '/mnt/Enterprise2/shirshak/BraTS2020_TrainingData/MICCAI_BraTS2020_TrainingData/*/*t1ce.nii'
        flair_location = '/mnt/Enterprise2/shirshak/BraTS2020_TrainingData/MICCAI_BraTS2020_TrainingData/*/*flair.nii'
        mask_location = '/mnt/Enterprise2/shirshak/BraTS2020_TrainingData/MICCAI_BraTS2020_TrainingData/*/*seg.nii'

        num_classes = 4
        num_channels_before_training = 3

        train_dataloader, test_dataloader, _,_ = get_from_loader_brats(t2_location, t1ce_location, flair_location, mask_location, batch_size)                        
    else:
        print("Error in the dataloader phase....please choose a correct data to use")
    
    # check for voxel shape and load in csv format
    # check_dataset(image_location, mask_location)

    model, num_epochs,optimizer, loss= training_phase(train_dataloader,test_dataloader, num_classes,num_channels_before_training,args)

