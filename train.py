from pathlib import Path
from einops import rearrange
import torch
from torch.optim import Adam
from torch.utils.data import DataLoader, Dataset
from torchvision.utils import save_image

from sample import sample
from network.unet import Unet
from forward import p_losses

from config import create_diffusion_config
from utils import num_to_groups

import numpy as np


# from datasets import load_dataset
# from torchvision.transforms import Compose
# from torchvision import transforms

# # load dataset from the hub
# dataset = load_dataset("fashion_mnist")
# image_size = 28
# channels = 1
# batch_size = 128

# transform = Compose(
#     [
#         transforms.RandomHorizontalFlip(),
#         transforms.ToTensor(),
#         transforms.Lambda(lambda t: (t * 2) - 1),
#     ]
# )


# def transforms(examples):
#     examples["pixel_values"] = [
#         transform(image.convert("L")) for image in examples["image"]
#     ]
#     del examples["image"]

#     return examples


# transformed_dataset = dataset.with_transform(transforms).remove_columns("label")

# # create dataloader
# dataloader = DataLoader(
#     transformed_dataset["train"], batch_size=batch_size, shuffle=True
# )


# load dataset
class SpritesDataset(Dataset):
    def __init__(self):
        self.ims = np.load("sprites_1788_16x16.npy").astype(np.float32)
        self.ims = (self.ims / 255) * 2 - 1
        self.ims = rearrange(self.ims, 'b h w c -> b c h w')

    def __len__(self):
        return len(self.ims)

    def __getitem__(self, idx):
        return dict(pixel_values=self.ims[idx])

dataset = SpritesDataset()
image_size = 16
channels = 3
batch_size = 128

dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

results_folder = Path("./results")
results_folder.mkdir(exist_ok=True)
for file in results_folder.glob("*"):
    file.unlink()
save_and_sample_every = 300

device = "cuda" if torch.cuda.is_available() else "cpu"

model = Unet(
    dim=image_size,
    channels=channels,
    dim_mults=(1, 2, 4),
)
model.to(device)

model_name = "sprites_16x3_linear_124.pth"

if Path(model_name).exists():
    model.load_state_dict(torch.load(model_name, map_location=device))

optimizer = Adam(model.parameters(), lr=1e-3)

timesteps = 200
config = create_diffusion_config(timesteps)

epochs = 5
try:
    for epoch in range(epochs):
        for step, batch in enumerate(dataloader):
            optimizer.zero_grad()

            batch_size = batch["pixel_values"].shape[0]
            batch = batch["pixel_values"].to(device)

            # Algorithm 1 line 3: sample t uniformally for every example in the batch
            t = torch.randint(0, timesteps, (batch_size,), device=device).long()

            loss = p_losses(model, batch, t, loss_type="huber")

            if step % 100 == 0:
                print("Loss:", loss.item())

            loss.backward()
            optimizer.step()

            # save generated images
            if step % save_and_sample_every == 0:
                milestone = (step + epoch * len(dataloader)) // save_and_sample_every
                batches = num_to_groups(4, batch_size)
                all_images_list = list(
                    map(
                        lambda n: torch.Tensor(
                            sample(
                                model,
                                image_size,
                                batch_size=n,
                                channels=channels,
                                config=config,
                            )[-1]
                        ),
                        batches,
                    )
                )
                all_images = torch.cat(all_images_list, dim=0)
                all_images = (all_images + 1) * 0.5
                save_image(
                    all_images, str(results_folder / f"sample-{milestone}.png"), nrow=6
                )
except KeyboardInterrupt:
    print("KeyboardInterrupt: saving model")
except Exception as e:
    print(f"Error: {e}")
    exit(1)

torch.save(model.state_dict(), model_name)
