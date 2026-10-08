"""Arquiteturas do comparativo temporal; janela passada, alvo fixo por horizonte."""
import math
import torch
from torch import nn

NAMES = ("CNN-1D", "LSTM", "GRU", "TCN", "Seq2Seq", "Transformer")

class Temporal(nn.Module):
    def __init__(self, name, features=11, hidden=32):
        super().__init__()
        self.name = name
        self.hidden = hidden
        self.output = nn.Linear(hidden, 1)
        if name in ("LSTM", "Seq2Seq"):
            self.encoder = nn.LSTMCell(features, hidden)
            if name == "Seq2Seq":
                self.decoder = nn.LSTMCell(1, hidden)
        elif name == "GRU":
            self.xz, self.hz = nn.Linear(features, hidden), nn.Linear(hidden, hidden, bias=False)
            self.xr, self.hr = nn.Linear(features, hidden), nn.Linear(hidden, hidden, bias=False)
            self.xn, self.hn = nn.Linear(features, hidden), nn.Linear(hidden, hidden, bias=False)
        elif name in ("CNN-1D", "TCN"):
            self.conv1 = nn.Conv1d(features, hidden, 3, padding=1)
            self.conv2 = nn.Conv1d(hidden, hidden, 3, padding=1)
            if name == "TCN":
                self.conv3 = nn.Conv1d(hidden, hidden, 3, padding=1)
        elif name == "Transformer":
            self.projection = nn.Linear(features, hidden)
            self.query, self.key, self.value = [nn.Linear(hidden, hidden) for _ in range(3)]
            self.norm1, self.norm2 = nn.LayerNorm(hidden), nn.LayerNorm(hidden)
            self.ff1, self.ff2 = nn.Linear(hidden, 64), nn.Linear(64, hidden)
        else:
            raise ValueError(name)

    def forward(self, x):
        if self.name in ("LSTM", "Seq2Seq"):
            h, c = None, None
            for v in x.unbind(1):
                h, c = self.encoder(v, None if h is None else (h, c))
            if self.name == "Seq2Seq":
                h, c = self.decoder(x.new_zeros(x.shape[0], 1), (h, c))
        elif self.name == "GRU":
            h = x.new_zeros(x.shape[0], self.hidden)
            for v in x.unbind(1):
                z = torch.sigmoid(self.xz(v) + self.hz(h))
                r = torch.sigmoid(self.xr(v) + self.hr(h))
                n = torch.tanh(self.xn(v) + self.hn(r * h))
                h = z * h + (1 - z) * n
        elif self.name in ("CNN-1D", "TCN"):
            v = torch.relu(self.conv1(x.transpose(1, 2)))
            out = torch.relu(self.conv2(v))
            if self.name == "TCN":
                out = torch.relu(self.conv3(torch.relu(out + v)))
            h = out[:, :, -1]
        else:
            v = self.projection(x)
            a = torch.softmax(self.query(v) @ self.key(v).transpose(1, 2) / math.sqrt(self.hidden), dim=-1)
            v = self.norm1(v + a @ self.value(v))
            h = self.norm2(v + self.ff2(torch.relu(self.ff1(v))))[:, -1]
        return self.output(h).reshape(-1)

def load_numpy(path, name):
    import numpy as np
    data = np.load(path, allow_pickle=False)
    model = Temporal(name)
    model.load_state_dict({k[3:]: torch.from_numpy(data[k].copy()) for k in data.files if k.startswith("w__")})
    model.eval()
    return model, data

def predict_numpy(path, name, sequences):
    import numpy as np
    model, data = load_numpy(path, name)
    x = (np.asarray(sequences, dtype=np.float32) - data["x_mean"]) / data["x_scale"]
    with torch.no_grad():
        y = model(torch.from_numpy(x.astype(np.float32))).numpy()
    return y * data["y_scale"] + data["y_mean"]
