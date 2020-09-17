# MegEngine is Licensed under the Apache License, Version 2.0 (the "License")
#
# Copyright (c) 2014-2020 Megvii Inc. All rights reserved.
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT ARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
from abc import abstractmethod
from typing import Tuple, Union

import numpy as np

from ..core.ops._internal import param_defs as P
from ..functional import conv2d, conv_transpose2d, local_conv2d, relu
from ..functional.types import _pair, _pair_nonzero
from ..tensor import Parameter
from . import init
from .module import Module


class _ConvNd(Module):
    """base class for convolution modules, including transposed conv"""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, Tuple[int, int]],
        stride: Union[int, Tuple[int, int]],
        padding: Union[int, Tuple[int, int]],
        dilation: Union[int, Tuple[int, int]],
        groups: int,
        bias: bool = True,
    ):
        super().__init__()
        if in_channels % groups != 0:
            raise ValueError("in_channels must be divisible by groups")
        if out_channels % groups != 0:
            raise ValueError("out_channels must be divisible by groups")
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding
        self.dilation = dilation
        self.groups = groups

        self.weight = Parameter(np.zeros(self._infer_weight_shape(), dtype=np.float32))
        self.bias = None
        if bias:
            self.bias = Parameter(np.zeros(self._infer_bias_shape(), dtype=np.float32))
        self.reset_parameters()

    @abstractmethod
    def _get_fanin(self):
        pass

    def reset_parameters(self) -> None:
        fanin = self._get_fanin()
        std = np.sqrt(1 / fanin)
        init.normal_(self.weight, 0.0, std)
        if self.bias is not None:
            init.zeros_(self.bias)

    @abstractmethod
    def _infer_weight_shape(self):
        pass

    @abstractmethod
    def _infer_bias_shape(self):
        pass


class Conv2d(_ConvNd):
    r"""Applies a 2D convolution over an input tensor.

    For instance, given an input of the size :math:`(N, C_{\text{in}}, H, W)`,
    this layer generates an output of the size
    :math:`(N, C_{\text{out}}, H_{\text{out}}, W_{\text{out}})` through the
    process described as below:

    .. math::
        \text{out}(N_i, C_{\text{out}_j}) = \text{bias}(C_{\text{out}_j}) +
        \sum_{k = 0}^{C_{\text{in}} - 1} \text{weight}(C_{\text{out}_j}, k) \star \text{input}(N_i, k)

    where :math:`\star` is the valid 2D cross-correlation operator,
    :math:`N` is a batch size, :math:`C` denotes a number of channels,
    :math:`H` is a height of input planes in pixels, and :math:`W` is
    width in pixels.

    When `groups == in_channels` and `out_channels == K * in_channels`,
    where K is a positive integer, this operation is also known as depthwise
    convolution.

    In other words, for an input of size :math:`(N, C_{in}, H_{in}, W_{in})`,
    a depthwise convolution with a depthwise multiplier `K`, can be constructed
    by arguments :math:`(in\_channels=C_{in}, out\_channels=C_{in} \times K, ..., groups=C_{in})`.

    :param in_channels: number of input channels.
    :param out_channels: number of output channels.
    :param kernel_size: size of weight on spatial dimensions. If kernel_size is
        an :class:`int`, the actual kernel size would be
        `(kernel_size, kernel_size)`. Default: 1
    :param stride: stride of the 2D convolution operation. Default: 1
    :param padding: size of the paddings added to the input on both sides of its
        spatial dimensions. Only zero-padding is supported. Default: 0
    :param dilation: dilation of the 2D convolution operation. Default: 1
    :param groups: number of groups to divide input and output channels into,
        so as to perform a "grouped convolution". When groups is not 1,
        in_channels and out_channels must be divisible by groups,
        and there would be an extra dimension at the beginning of the weight's
        shape. Specifically, the shape of weight would be `(groups,
        out_channel // groups, in_channels // groups, *kernel_size)`.
    :param bias: whether to add a bias onto the result of convolution. Default:
        True
    :param conv_mode: Supports `CROSS_CORRELATION` or `CONVOLUTION`. Default:
        `CROSS_CORRELATION`
    :param compute_mode: When set to `DEFAULT`, no special requirements will be
        placed on the precision of intermediate results. When set to `FLOAT32`,
        float32 would be used for accumulator and intermediate result, but only
        effective when input and output are of float16 dtype.

    Examples:

    .. testcode::

        import numpy as np
        import megengine as mge
        import megengine.module as M

        m = M.Conv2d(in_channels=3, out_channels=1, kernel_size=3)
        inp = mge.tensor(np.arange(0, 96).astype("float32").reshape(2, 3, 4, 4))
        oup = m(inp)
        print(oup.shape)

    Outputs:

    .. testoutput::

        (2, 1, 2, 2)

    """

    _conv_mode_type = P.Convolution.Mode
    _compute_mode_type = P.Convolution.ComputeMode

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, Tuple[int, int]],
        stride: Union[int, Tuple[int, int]] = 1,
        padding: Union[int, Tuple[int, int]] = 0,
        dilation: Union[int, Tuple[int, int]] = 1,
        groups: int = 1,
        bias: bool = True,
        conv_mode: str = "CROSS_CORRELATION",
        compute_mode: str = "DEFAULT",
    ):
        kernel_size = _pair_nonzero(kernel_size)
        stride = _pair_nonzero(stride)
        padding = _pair(padding)
        dilation = _pair_nonzero(dilation)
        self.conv_mode = self._conv_mode_type.convert(conv_mode)
        self.compute_mode = self._compute_mode_type.convert(compute_mode)
        super().__init__(
            in_channels,
            out_channels,
            kernel_size,
            stride,
            padding,
            dilation,
            groups,
            bias,
        )

    def _get_fanin(self):
        kh, kw = self.kernel_size
        ic = self.in_channels
        return kh * kw * ic

    def _infer_weight_shape(self):
        group = self.groups
        ichl = self.in_channels
        ochl = self.out_channels
        kh, kw = self.kernel_size
        if group == 1:
            # Assume format is NCHW
            return (ochl, ichl, kh, kw)

        assert (
            ichl % group == 0 and ochl % group == 0
        ), "invalid config: input_channels={} output_channels={} group={}".format(
            ichl, ochl, group
        )
        # Assume format is NCHW
        return (group, ochl // group, ichl // group, kh, kw)

    def _infer_bias_shape(self):
        # Assume format is NCHW
        return (1, self.out_channels, 1, 1)

    def calc_conv(self, inp, weight, bias):
        return conv2d(
            inp,
            weight,
            bias,
            self.stride,
            self.padding,
            self.dilation,
            self.groups,
            self.conv_mode,
            self.compute_mode,
        )

    def forward(self, inp):
        return self.calc_conv(inp, self.weight, self.bias)


class ConvTranspose2d(_ConvNd):
    r"""Applies a 2D transposed convolution over an input tensor.

    This module is also known as a deconvolution or a fractionally-strided convolution.
    :class:`ConvTranspose2d` can ben seen as the gradient of :class:`Conv2d` operation
    with respect to its input.

    Convolution usually reduces the size of input, while transposed convolution works
    the opposite way, transforming a smaller input to a larger output while preserving the
    connectivity pattern.

    :param in_channels: number of input channels.
    :param out_channels: number of output channels.
    :param kernel_size: size of weight on spatial dimensions. If ``kernel_size`` is
        an :class:`int`, the actual kernel size would be
        ``(kernel_size, kernel_size)``. Default: 1
    :param stride: stride of the 2D convolution operation. Default: 1
    :param padding: size of the paddings added to the input on both sides of its
        spatial dimensions. Only zero-padding is supported. Default: 0
    :param dilation: dilation of the 2D convolution operation. Default: 1
    :param groups: number of groups to divide input and output channels into,
        so as to perform a "grouped convolution". When ``groups`` is not 1,
        ``in_channels`` and ``out_channels`` must be divisible by ``groups``,
        and there would be an extra dimension at the beginning of the weight's
        shape. Specifically, the shape of weight would be ``(groups,
        out_channels // groups, in_channels // groups, *kernel_size)``. Default: 1
    :param bias: wether to add a bias onto the result of convolution. Default:
        True
    :param conv_mode: Supports `CROSS_CORRELATION` or `CONVOLUTION`. Default:
        `CROSS_CORRELATION`
    :param compute_mode: When set to `DEFAULT`, no special requirements will be
        placed on the precision of intermediate results. When set to `FLOAT32`,
        float32 would be used for accumulator and intermediate result, but only
        effective when input and output are of float16 dtype.
    """

    _conv_mode_type = P.Convolution.Mode
    _compute_mode_type = P.Convolution.ComputeMode

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: Union[int, Tuple[int, int]],
        stride: Union[int, Tuple[int, int]] = 1,
        padding: Union[int, Tuple[int, int]] = 0,
        dilation: Union[int, Tuple[int, int]] = 1,
        groups: int = 1,
        bias: bool = True,
        conv_mode: str = "CROSS_CORRELATION",
        compute_mode: str = "DEFAULT",
    ):
        kernel_size = _pair_nonzero(kernel_size)
        stride = _pair_nonzero(stride)
        padding = _pair(padding)
        dilation = _pair_nonzero(dilation)
        self.conv_mode = self._conv_mode_type.convert(conv_mode)
        self.compute_mode = self._compute_mode_type.convert(compute_mode)
        super().__init__(
            in_channels,
            out_channels,
            kernel_size,
            stride,
            padding,
            dilation,
            groups,
            bias,
        )

    def _get_fanin(self):
        kh, kw = self.kernel_size
        oc = self.out_channels
        return kh * kw * oc

    def _infer_weight_shape(self):
        group = self.groups
        ichl = self.in_channels
        ochl = self.out_channels
        kh, kw = self.kernel_size
        if group == 1:
            # Assume format is NCHW
            return (ichl, ochl, kh, kw)

        assert (
            ichl % group == 0 and ochl % group == 0
        ), "invalid config: input_channels={} output_channels={} group={}".format(
            ichl, ochl, group
        )
        # Assume format is NCHW
        return (group, ichl // group, ochl // group, kh, kw)

    def _infer_bias_shape(self):
        # Assume format is NCHW
        return (1, self.out_channels, 1, 1)

    def forward(self, inp):
        return conv_transpose2d(
            inp,
            self.weight,
            self.bias,
            self.stride,
            self.padding,
            self.dilation,
            self.groups,
            self.conv_mode,
            self.compute_mode,
        )


class LocalConv2d(Conv2d):
    r"""Applies a spatial convolution with untied kernels over an input 4D tensor.
    It is also known as the locally connected layer.

    :param in_channels: number of input channels.
    :param out_channels: number of output channels.
    :param input_height: the height of the input images.
    :param input_width: the width of the input images.
    :param kernel_size: size of weight on spatial dimensions. If kernel_size is
        an :class:`int`, the actual kernel size would be
        `(kernel_size, kernel_size)`. Default: 1
    :param stride: stride of the 2D convolution operation. Default: 1
    :param padding: size of the paddings added to the input on both sides of its
        spatial dimensions. Only zero-padding is supported. Default: 0
    :param groups: number of groups to divide input and output channels into,
        so as to perform a "grouped convolution". When groups is not 1,
        in_channels and out_channels must be divisible by groups.
        The shape of weight is `(groups, output_height, output_width,
        in_channels // groups, *kernel_size, out_channels // groups)`.
    """

    _conv_mode_type = P.Convolution.Mode

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        input_height: int,
        input_width: int,
        kernel_size: Union[int, Tuple[int, int]],
        stride: Union[int, Tuple[int, int]] = 1,
        padding: Union[int, Tuple[int, int]] = 0,
        dilation: Union[int, Tuple[int, int]] = 1,
        groups: int = 1,
        conv_mode: str = "CROSS_CORRELATION",
    ):
        self.input_height = input_height
        self.input_width = input_width
        super().__init__(
            in_channels,
            out_channels,
            kernel_size,
            stride,
            padding,
            dilation,
            groups,
            bias=False,
        )

    def _infer_weight_shape(self):
        group = self.groups
        output_height = (
            self.input_height + self.padding[0] * 2 - self.kernel_size[0]
        ) // self.stride[0] + 1
        output_width = (
            self.input_width + self.padding[1] * 2 - self.kernel_size[1]
        ) // self.stride[1] + 1
        # Assume format is NCHW
        return (
            group,
            output_height,
            output_width,
            self.in_channels // group,
            self.kernel_size[0],
            self.kernel_size[1],
            self.out_channels // group,
        )

    def forward(self, inp):
        return local_conv2d(
            inp,
            self.weight,
            None,
            self.stride,
            self.padding,
            self.dilation,
            self.conv_mode,
        )


class ConvRelu2d(Conv2d):
    r"""
    A fused :class:`~.Module` including Conv2d and relu. Could be replaced
    with :class:`~.QATModule` version :class:`~.qat.conv.ConvRelu2d` using
    :func:`~.quantize.quantize_qat`.
    """

    def forward(self, inp):
        return relu(self.calc_conv(inp, self.weight, self.bias))
