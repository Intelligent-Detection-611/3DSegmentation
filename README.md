# 3DSegmentation Version 0.1

The initial version of 3DFusion modifies the traditional 2D multimodal image fusion network to enable training on 3D medical data in NIfTI format.


## Recommended Environment

To be continued...

More detailed environment requirements can be found in ```requirements.txt```. 

## To Training

### 1. Prepare the SegTHOR dataset

The dataset format is as follows:

```shell
 Data/
 ├── train
 │   ├── Patient_01├──GT.nii.gz
				   ├──Patient_01.nii.gz
 │   ├── Patient_02├──......
 │   ├── ......
 ├── test
 │   ├── Patient_41.nii.gz
 │   ├── Patient_42.nii.gz
 │   ├── ......
```

### 2. Training the 3D Segmentation Network
#### (Specific information is to be added.)
```shell
python train.py
```

## To Testing
### (Specific information is to be added.)
```shell
python test.py
```

# TODO


## If this work is helpful to you, please cite it as：
```

```
