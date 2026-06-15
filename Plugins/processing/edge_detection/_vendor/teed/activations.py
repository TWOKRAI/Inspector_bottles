"""Функции активации для TEED.

Объединены Fsmish (функциональная) и Smish (nn.Module) из оригинального репозитория.
Источник: https://github.com/xavysp/TEED/tree/main/utils/AF

Smish: Wang, Xueliang, Honge Ren, and Achuan Wang.
"Smish: A Novel Activation Function for Deep Learning Methods."
Electronics 11.4 (2022): 540.

smish(x) = x * tanh(ln(1 + sigmoid(x)))

Перенесено как есть из projects_obsidian/sketch_robot/_vendor/teed/activations.py.
"""

import torch
import torch.nn as nn


@torch.jit.script
def smish(input: torch.Tensor) -> torch.Tensor:
    """Применяет smish поэлементно: x * tanh(ln(1 + sigmoid(x)))"""
    return input * torch.tanh(torch.log(1 + torch.sigmoid(input)))


class Smish(nn.Module):
    """Smish активация как nn.Module."""

    def forward(self, input: torch.Tensor) -> torch.Tensor:
        return smish(input)
