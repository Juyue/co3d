# Copyright (c) Facebook, Inc. and its affiliates.
# All rights reserved.

# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.


import os
import unittest
import torch
import torchvision

from visdom import Visdom

from dataset.co3d_dataset import Co3dDataset
from dataset.visualize import get_co3d_sequence_pointcloud
from dataset.dataset_zoo import DATASET_ROOT
from tools.camera_utils import select_cameras
from tools.point_cloud_utils import render_point_cloud_pytorch3d
from pytorch3d.vis.plotly_vis import plot_scene


class TestDatasetVisualize(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)
        category = 'skateboard'
        dataset_root = DATASET_ROOT
        frame_file = os.path.join(dataset_root, category, 'frame_annotations.jgz')
        sequence_file = os.path.join(dataset_root, category, 'sequence_annotations.jgz')
        self.image_size = 256
        self.datasets = {
            'simple': Co3dDataset(
                frame_annotations_file=frame_file,
                sequence_annotations_file=sequence_file,
                dataset_root=dataset_root,
                image_height=self.image_size,
                image_width=self.image_size,
                box_crop=True,
                load_point_clouds=True,
            ),
            'nonsquare': Co3dDataset(
                frame_annotations_file=frame_file,
                sequence_annotations_file=sequence_file,
                dataset_root=dataset_root,
                image_height=self.image_size,
                image_width=self.image_size // 2,
                box_crop=True,
                load_point_clouds=True,
            ),
            'nocrop': Co3dDataset(
                frame_annotations_file=frame_file,
                sequence_annotations_file=sequence_file,
                dataset_root=dataset_root,
                image_height=self.image_size,
                image_width=self.image_size // 2,
                box_crop=False,
                load_point_clouds=True,
            ),
        }
        self.visdom = Visdom()
        if not self.visdom.check_connection():
            print('Visdom server not running! Disabling visdom visualisations.')
            self.visdom = None
        
    def _render_one_pointcloud(self, point_cloud, cameras, render_size):
        (
            _image_render, _, _
        ) = render_point_cloud_pytorch3d(
            cameras,
            point_cloud,
            render_size=render_size,
            point_radius=1e-2,
            topk=10,
            bg_color=0.0,
        )
        return _image_render.clamp(0.0, 1.0)

    def test_one(self):
        """Test dataset visualisation."""
        for max_frames in (16,):
            for load_dataset_point_cloud in (True, False):
                for dataset_key in self.datasets:
                    self._gen_and_render_pointcloud(
                        max_frames, load_dataset_point_cloud, dataset_key
                    )

    def _gen_and_render_pointcloud(
        self, max_frames, load_dataset_point_cloud, dataset_key
    ):
        dataset = self.datasets[dataset_key]
        # load the point cloud of the first sequence
        sequence_show = list(dataset.seq_annots.keys())[0]
        device = torch.device('cuda:0')

        point_cloud, sequence_frame_data = get_co3d_sequence_pointcloud(
            dataset,
            sequence_name=sequence_show,
            mask_points=True,
            max_frames=max_frames,
            num_workers=10,
            load_dataset_point_cloud=load_dataset_point_cloud,
        )

        # render on gpu
        point_cloud = point_cloud.to(device)
        cameras = sequence_frame_data.camera.to(device)

        # render the point_cloud from the viewpoint of loaded cameras
        images_render = torch.cat([
            self._render_one_pointcloud(
                point_cloud,
                select_cameras(cameras, frame_i),
                (dataset.image_height, dataset.image_width,),
            ) for frame_i in range(len(cameras))
        ]).cpu()
        images_gt_and_render = torch.cat(
            [sequence_frame_data.image_rgb, images_render], dim=3
        )

        imfile = os.path.join(
            os.path.split(os.path.abspath(__file__))[0],
            f'test_dataset_visualize'
            + f'_max_frames={max_frames}'
            + f'_load_pcl={load_dataset_point_cloud}'
            + f'_dataset_key={dataset_key}.png',
        )
        print(f'Exporting image {imfile}.')
        torchvision.utils.save_image(images_gt_and_render, imfile, nrow=2)

        if self.visdom is not None:
            test_name = f"{max_frames}_{load_dataset_point_cloud}_{dataset_key}"
            self.visdom.images(
                images_gt_and_render,
                env='test_dataset_visualize',
                win=f'pcl_renders_{test_name}',
                opts={'title': f'pcl_renders_{test_name}'},
            )
            plotlyplot = plot_scene(
                {
                    'scene_batch': {
                        'cameras': cameras,
                        'point_cloud': point_cloud,
                    }
                },
                camera_scale=1.0,
                pointcloud_max_points=10000,
                pointcloud_marker_size=1.0,
            )
            self.visdom.plotlyplot(
                plotlyplot,
                env='test_dataset_visualize',
                win=f'pcl_{test_name}',
            )