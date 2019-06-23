import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


class Angular_mc_loss(nn.Module):
    def __init__(self, alpha=45, in_degree=True):
        super(Angular_mc_loss, self).__init__()
        if in_degree:
            alpha = np.deg2rad(alpha)
        self.sq_tan_alpha = np.tan(alpha) ** 2

    def forward(self, f, f_p):
        # xp = cuda.get_array_module(f)
        n_pairs = len(f)
        # print(f.size())
        # first and second term of f_{a,p,n}
        # 論文だと転置の方向が違うかも
        # 結局logsumexpでaxis=1だから変わらんけどさ
        term1 = 4 * self.sq_tan_alpha * torch.matmul(f + f_p, torch.transpose(f_p, 0, 1))
        term2 = 2 * (1 + self.sq_tan_alpha) * torch.sum(f * f_p, keepdim=True, dim=1)
        # term2 = 2 * (1 + sq_tan_alpha) * F.batch_matmul(f, f_p, transa=True).reshape(n_pairs, 1)

        f_apn = term1 - term2
        # multiply zero to diagonal components of f_apn
        # print(f_apn.type())
        # print(n_pairs.type())
        # print(f_apn.type())
        # print(torch.ones_like(f_apn).type(), f_apn.type(), torch.eye(n_pairs, dtype=f_apn.type()).type())
        mask = torch.ones_like(f_apn) - torch.eye(n_pairs).cuda()
        f_apn = f_apn * mask
        # print(f_apn)
        return torch.mean(torch.logsumexp(f_apn, dim=1))

class my_AngularLoss(nn.Module):
    """
    Angular loss
    Wang, Jian. "Deep Metric Learning with Angular Loss," CVPR, 2017
    https://arxiv.org/pdf/1708.01682.pdf
    """

    def __init__(self, l2_reg=0.02, angle_bound=1., lambda_ang=2):
        super(my_AngularLoss, self).__init__()
        self.l2_reg = l2_reg
        self.angle_bound = angle_bound
        self.lambda_ang = lambda_ang
        self.softplus = nn.Softplus()

    def forward(self, anchors, positives, negatives):

        losses = self.angular_loss(anchors, positives, negatives, self.angle_bound) + self.l2_reg * self.l2_loss(anchors, positives)

        return losses

    @staticmethod
    def angular_loss(anchors, positives, negatives, angle_bound=1.):
        """
        Calculates angular loss
        :param anchors: A torch.Tensor, (n, embedding_size)
        :param positives: A torch.Tensor, (n, embedding_size)
        :param negatives: A torch.Tensor, (n, n-1, embedding_size)
        :param angle_bound: tan^2 angle
        :return: A scalar
        """

        anchors = torch.unsqueeze(anchors, dim=1) # (batch_size, 1, embedding_size)
        positives = torch.unsqueeze(positives, dim=1) # (batch_size, 1, embedding_size)
        batch_size = anchors.size()[0]
        negatives = [negatives[i*5:(i+1)*5] for i in range(batch_size)]
        negatives = torch.stack(negatives)# (batch_size, n-1, embedding_size)

        anchors, positives, negatives = anchors.cuda(), positives.cuda(), negatives.cuda()

        x = 4. * angle_bound * torch.matmul((anchors + positives), negatives.transpose(1, 2)) - 2. * (1. + angle_bound) * torch.matmul(anchors, positives.transpose(1, 2))  # (n, 1, n-1)

        print(x.size())
        # Preventing overflow
        with torch.no_grad():
            t = torch.max(x, dim=2)[0] # (batch_size, 1)
        print(t.size())

        x = torch.exp(x - t.unsqueeze(dim=1))
        x = torch.log(torch.exp(-t) + torch.sum(x, 2))
        loss = torch.mean(t + x)

        return loss

    @staticmethod
    def l2_loss(anchors, positives):
        """
        Calculates L2 norm regularization loss
        :param anchors: A torch.Tensor, (n, embedding_size)
        :param positives: A torch.Tensor, (n, embedding_size)
        :return: A scalar
        """
        return torch.sum(anchors ** 2 + positives ** 2) / anchors.shape[0]



class NPairLoss(nn.Module):
    """
    N-Pair loss
    Sohn, Kihyuk. "Improved Deep Metric Learning with Multi-class N-pair Loss Objective," Advances in Neural Information
    Processing Systems. 2016.
    http://papers.nips.cc/paper/6199-improved-deep-metric-learning-with-multi-class-n-pair-loss-objective
    """

    def __init__(self, l2_reg=0.02):
        super(NPairLoss, self).__init__()
        self.l2_reg = l2_reg

    def forward(self, anchors, positives, negatives):
        """
        anchors (batch_size, embedding_size)
        positives (batch_size, embedding_size)
        negatives (batch_size*(n-1), embedding_size)
        """
        batch_size = anchors.size()[0]
        negatives = [negatives[i*5:(i+1)*5] for i in range(batch_size)]
        negatives = torch.stack(negatives)# (batch_size, n-1, embedding_size)

        # print(anchors)
        anchors, positives, negatives = anchors.cuda(), positives.cuda(), negatives.cuda()
        losses = self.n_pair_loss(anchors, positives, negatives) \
            + self.l2_reg * self.l2_loss(anchors, positives)
        # print(self.n_pair_loss(anchors, positives, negatives), self.l2_reg * self.l2_loss(anchors, positives))
        return losses


    @staticmethod
    def n_pair_loss(anchors, positives, negatives):
        """
        Calculates N-Pair loss
        :param anchors: A torch.Tensor, (n, embedding_size)
        :param positives: A torch.Tensor, (n, embedding_size)
        :param negatives: A torch.Tensor, (n, n-1, embedding_size)
        :return: A scalar
        """
        anchors = torch.unsqueeze(anchors, dim=1)  # (n, 1, embedding_size)
        positives = torch.unsqueeze(positives, dim=1)  # (n, 1, embedding_size)

        x = torch.matmul(anchors, (negatives - positives).transpose(1, 2))  # (n, 1, n-1)
        x = torch.sum(torch.exp(x), 2)  # (n, 1)
        loss = torch.mean(torch.log(1+x))
        return loss

    @staticmethod
    def l2_loss(anchors, positives):
        """
        Calculates L2 norm regularization loss
        :param anchors: A torch.Tensor, (n, embedding_size)
        :param positives: A torch.Tensor, (n, embedding_size)
        :return: A scalar
        """
        return torch.sum(anchors ** 2 + positives ** 2) / anchors.shape[0]