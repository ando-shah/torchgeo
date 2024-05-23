# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""ETCI 2021 dataset."""

import glob
import os
from collections.abc import Callable

import matplotlib.pyplot as plt
import numpy as np
import torch
from matplotlib.figure import Figure
from PIL import Image
from torch import Tensor

from .errors import DatasetNotFoundError
from .geo import NonGeoDataset
from .utils import download_and_extract_archive


class ETCI2021(NonGeoDataset):
    """ETCI 2021 Flood Detection dataset.

    The `ETCI2021 <https://nasa-impact.github.io/etci2021/>`_
    dataset is a dataset for flood detection

    Dataset features:

    * 33,405 VV & VH Sentinel-1 Synthetic Aperture Radar (SAR) images
    * 2 binary masks per image representing water body & flood, respectively
    * 2 polarization band images (VV, VH) of 3 RGB channels per band
    * 3 RGB channels per band generated by the Hybrid Pluggable Processing
      Pipeline (hyp3)
    * Images with 5x20m per pixel resolution (256x256) px) taken in
      Interferometric Wide Swath acquisition mode
    * Flood events from 5 different regions

    Dataset format:

    * VV band three-channel png
    * VH band three-channel png
    * water body mask single-channel png where no water body = 0, water body = 255
    * flood mask single-channel png where no flood = 0, flood = 255

    Dataset classes:

    1. no flood/water
    2. flood/water

    If you use this dataset in your research, please add the following to your
    acknowledgements section::

        The authors would like to thank the NASA Earth Science Data Systems Program,
        NASA Digital Transformation AI/ML thrust, and IEEE GRSS for organizing
        the ETCI competition.
    """

    bands = ['VV', 'VH']
    masks = ['flood', 'water_body']
    metadata = {
        'train': {
            'filename': 'train.zip',
            'md5': '1e95792fe0f6e3c9000abdeab2a8ab0f',
            'directory': 'train',
            'url': 'https://drive.google.com/file/d/14HqNW5uWLS92n7KrxKgDwUTsSEST6LCr',
        },
        'val': {
            'filename': 'val_with_ref_labels.zip',
            'md5': 'fd18cecb318efc69f8319f90c3771bdf',
            'directory': 'test',
            'url': 'https://drive.google.com/file/d/19sriKPHCZLfJn_Jmk3Z_0b3VaCBVRVyn',
        },
        'test': {
            'filename': 'test_without_ref_labels.zip',
            'md5': 'da9fa69e1498bd49d5c766338c6dac3d',
            'directory': 'test_internal',
            'url': 'https://drive.google.com/file/d/1rpMVluASnSHBfm2FhpPDio0GyCPOqg7E',
        },
    }

    def __init__(
        self,
        root: str = 'data',
        split: str = 'train',
        transforms: Callable[[dict[str, Tensor]], dict[str, Tensor]] | None = None,
        download: bool = False,
        checksum: bool = False,
    ) -> None:
        """Initialize a new ETCI 2021 dataset instance.

        Args:
            root: root directory where dataset can be found
            split: one of "train", "val", or "test"
            transforms: a function/transform that takes input sample and its target as
                entry and returns a transformed version
            download: if True, download dataset and store it in the root directory
            checksum: if True, check the MD5 of the downloaded files (may be slow)

        Raises:
            AssertionError: if ``split`` argument is invalid
            DatasetNotFoundError: If dataset is not found and *download* is False.
        """
        assert split in self.metadata.keys()

        self.root = root
        self.split = split
        self.transforms = transforms
        self.checksum = checksum

        if download:
            self._download()

        if not self._check_integrity():
            raise DatasetNotFoundError(self)

        self.files = self._load_files(self.root, self.split)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return an index within the dataset.

        Args:
            index: index to return

        Returns:
            data and label at that index
        """
        files = self.files[index]
        vv = self._load_image(files['vv'])
        vh = self._load_image(files['vh'])
        water_mask = self._load_target(files['water_mask'])

        if self.split != 'test':
            flood_mask = self._load_target(files['flood_mask'])
            mask = torch.stack(tensors=[water_mask, flood_mask], dim=0)
        else:
            mask = water_mask.unsqueeze(0)

        image = torch.cat(tensors=[vv, vh], dim=0)
        sample = {'image': image, 'mask': mask}

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample

    def __len__(self) -> int:
        """Return the number of data points in the dataset.

        Returns:
            length of the dataset
        """
        return len(self.files)

    def _load_files(self, root: str, split: str) -> list[dict[str, str]]:
        """Return the paths of the files in the dataset.

        Args:
            root: root dir of dataset
            split: subset of dataset, one of [train, val, test]

        Returns:
            list of dicts containing paths for each pair of vv, vh,
            water body mask, flood mask (train/val only)
        """
        files = []
        directory = self.metadata[split]['directory']
        folders = sorted(glob.glob(os.path.join(root, directory, '*')))
        folders = [os.path.join(folder, 'tiles') for folder in folders]
        for folder in folders:
            vvs = sorted(glob.glob(os.path.join(folder, 'vv', '*.png')))
            vhs = [vv.replace('vv', 'vh') for vv in vvs]
            water_masks = [
                vv.replace('_vv.png', '.png').replace('vv', 'water_body_label')
                for vv in vvs
            ]

            if split != 'test':
                flood_masks = [
                    vv.replace('_vv.png', '.png').replace('vv', 'flood_label')
                    for vv in vvs
                ]

                for vv, vh, flood_mask, water_mask in zip(
                    vvs, vhs, flood_masks, water_masks
                ):
                    files.append(
                        dict(vv=vv, vh=vh, flood_mask=flood_mask, water_mask=water_mask)
                    )
            else:
                for vv, vh, water_mask in zip(vvs, vhs, water_masks):
                    files.append(dict(vv=vv, vh=vh, water_mask=water_mask))

        return files

    def _load_image(self, path: str) -> Tensor:
        """Load a single image.

        Args:
            path: path to the image

        Returns:
            the image
        """
        filename = os.path.join(path)
        with Image.open(filename) as img:
            array: np.typing.NDArray[np.int_] = np.array(img.convert('RGB'))
            tensor = torch.from_numpy(array).float()
            # Convert from HxWxC to CxHxW
            tensor = tensor.permute((2, 0, 1))
            return tensor

    def _load_target(self, path: str) -> Tensor:
        """Load the target mask for a single image.

        Args:
            path: path to the image

        Returns:
            the target mask
        """
        filename = os.path.join(path)
        with Image.open(filename) as img:
            array: np.typing.NDArray[np.int_] = np.array(img.convert('L'))
            tensor = torch.from_numpy(array)
            tensor = torch.clamp(tensor, min=0, max=1)
            tensor = tensor.to(torch.long)
            return tensor

    def _check_integrity(self) -> bool:
        """Checks the integrity of the dataset structure.

        Returns:
            True if the dataset directories and split files are found, else False
        """
        directory = self.metadata[self.split]['directory']
        dirpath = os.path.join(self.root, directory)
        if not os.path.exists(dirpath):
            return False
        return True

    def _download(self) -> None:
        """Download the dataset and extract it."""
        if self._check_integrity():
            print('Files already downloaded and verified')
            return

        download_and_extract_archive(
            self.metadata[self.split]['url'],
            self.root,
            filename=self.metadata[self.split]['filename'],
            md5=self.metadata[self.split]['md5'] if self.checksum else None,
        )

    def plot(
        self,
        sample: dict[str, Tensor],
        show_titles: bool = True,
        suptitle: str | None = None,
    ) -> Figure:
        """Plot a sample from the dataset.

        Args:
            sample: a sample returned by :meth:`__getitem__`
            show_titles: flag indicating whether to show titles above each panel
            suptitle: optional string to use as a suptitle

        Returns:
            a matplotlib Figure with the rendered sample
        """
        vv = np.rollaxis(sample['image'][:3].numpy(), 0, 3)
        vh = np.rollaxis(sample['image'][3:].numpy(), 0, 3)
        mask = sample['mask'].squeeze(0)

        showing_flood_mask = mask.shape[0] == 2
        showing_predictions = 'prediction' in sample
        num_panels = 3
        if showing_flood_mask:
            water_mask = mask[0].numpy()
            flood_mask = mask[1].numpy()
            num_panels += 1
        else:
            water_mask = mask.numpy()

        if showing_predictions:
            predictions = sample['prediction'].numpy()
            num_panels += 1

        fig, axs = plt.subplots(1, num_panels, figsize=(num_panels * 4, 3))
        axs[0].imshow(vv)
        axs[0].axis('off')
        axs[1].imshow(vh)
        axs[1].axis('off')
        axs[2].imshow(water_mask)
        axs[2].axis('off')
        if show_titles:
            axs[0].set_title('VV')
            axs[1].set_title('VH')
            axs[2].set_title('Water mask')

        idx = 0
        if showing_flood_mask:
            axs[3 + idx].imshow(flood_mask)
            axs[3 + idx].axis('off')
            if show_titles:
                axs[3 + idx].set_title('Flood mask')
            idx += 1

        if showing_predictions:
            axs[3 + idx].imshow(predictions)
            axs[3 + idx].axis('off')
            if show_titles:
                axs[3 + idx].set_title('Predictions')
            idx += 1

        if suptitle is not None:
            plt.suptitle(suptitle)
        return fig
