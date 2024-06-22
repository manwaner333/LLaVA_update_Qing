import json
import pickle
import os
import tqdm
import numpy as np
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
import random

clear_figure = True
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, auc, precision_recall_curve

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("device:", device)
# np.random.seed(42)
# torch.manual_seed(42)

def set_random_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False



class Probe(nn.Module):
    def __init__(self, input_dim):
        super(Probe, self).__init__()
        self.input_dim = input_dim
        self.fc1 = nn.Linear(input_dim, 32)
        self.ln1 = nn.LayerNorm(32)
        self.fc2 = nn.Linear(32, 1)
        self.relu = nn.ReLU()
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.relu(self.ln1(self.fc1(x)))  # 添加 LayerNorm
        x = self.fc2(x)  # 添加 LayerNorm
        return self.sigmoid(x)



def train(model, criterion, optimizer, train_loader, test_loader, num_epochs, device):
    model.train()
    best_accuracy, best_precision, best_recall, best_f1, best_pr_auc = 0, 0, 0, 0, 0

    for epoch in range(num_epochs):
        running_loss = 0.0
        train_count = 0
        for batch in train_loader:
            inputs, labels = batch['data'].to(device), batch['label'].to(device)
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels.unsqueeze(1).float())
            loss.backward()
            optimizer.step()
            train_count += torch.sum(labels == 1).item()
            running_loss += loss.item()
        print(f"Epoch {epoch + 1}/{num_epochs}, Loss: {running_loss / len(train_loader)}")
        print("Train:")
        accuracy, precision, recall, f1, pr_auc, all_outputs_prob, all_labels, count = evaluate(model, train_loader,
                                                                                                device)
        print("Test:")
        accuracy, precision, recall, f1, pr_auc, all_outputs_prob, all_labels, count = evaluate(model, test_loader,
                                                                                                device)
        # print(all_outputs_prob)

        if f1 > best_f1:
            best_accuracy, best_precision, best_recall, best_f1, best_pr_auc, all_outputs_prob, all_labels = accuracy, precision, recall, f1, pr_auc, all_outputs_prob, all_labels
    # torch.save(model.state_dict(), 'Qing/safety_update/model.pth')
    # print("Final Res: ", best_accuracy, best_precision, best_recall, best_f1, best_pr_auc)
    return accuracy, precision, recall, f1, pr_auc, count, train_count
    # return best_accuracy, best_precision, best_recall, best_f1, best_pr_auc, count, train_count


def evaluate(model, test_loader, device):
    model.eval()
    all_labels = []
    all_predictions = []
    all_outputs_prob = []

    TP, FP, FN = 0, 0, 0

    with torch.no_grad():
        count = 0
        for batch in test_loader:
            inputs, labels = batch['data'].to(device), batch['label'].to(device)
            outputs = model(inputs)
            predicted = torch.round(outputs)

            # Store labels and predictions
            all_labels.extend(labels.cpu().numpy())
            all_predictions.extend(predicted.cpu().numpy())
            all_outputs_prob.extend(outputs.cpu().numpy())
            TP += ((predicted == 1) & (labels.unsqueeze(1) == 1)).sum().item()
            FP += ((predicted == 1) & (labels.unsqueeze(1) == 0)).sum().item()
            FN += ((predicted == 0) & (labels.unsqueeze(1) == 1)).sum().item()
            count += torch.sum(labels == 1).item()
    # Convert lists to numpy arrays for scikit-learn
    all_labels = np.array(all_labels)
    all_predictions = np.array(all_predictions).flatten()  # Flatten in case the predictions are in a column vector

    # Calculate metrics using scikit-learn
    accuracy = accuracy_score(all_labels, all_predictions)
    precision = precision_score(all_labels, all_predictions, pos_label=1)
    recall = recall_score(all_labels, all_predictions, pos_label=1)
    f1 = f1_score(all_labels, all_predictions, pos_label=1)

    precision_curve, recall_curve, _ = precision_recall_curve(all_labels, all_outputs_prob)
    pr_auc = auc(recall_curve, precision_curve)
    new_precision = TP / (TP + FP) if TP + FP > 0 else 0
    new_recall = TP / (TP + FN) if TP + FN > 0 else 0
    print(
        f"Accuracy: {accuracy:.2f} Precision: {precision:.2f} Recall: {recall:.2f} F1 Score: {f1:.2f} PR-AUC: {pr_auc:.2f}")
    # print(all_predictions)
    return accuracy, precision, recall, f1, pr_auc, all_outputs_prob, all_labels, count


class CustomDataset(Dataset):
    def __init__(self, data, labels):
        self.data = data
        self.labels = labels

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        sample = {'data': torch.tensor(self.data[idx], dtype=torch.float32),
                  'label': torch.tensor(self.labels[idx], dtype=torch.float32)}
        return sample

def generate_data(file1=None, file2=None):
    res = {}
    for i in range(0, 32):
        for j in range(0, 32):
            res[f"layer_{i}_head_{j}"] = {'activations': [], 'labels': []}

    if file1 is not None:
        with open(file1, "r") as file_1:  # train_file
            for line in file_1:
                item = json.loads(line)
                safe = item["safe"]
                block_activations = item['block_activations']
                for layer_num in range(0, 32):
                    layer_activations = block_activations[str(layer_num)][0]
                    for head_num in range(len(layer_activations)):
                        res[f"layer_{layer_num}_head_{head_num}"]['activations'].append(layer_activations[head_num])
                        res[f"layer_{layer_num}_head_{head_num}"]['labels'].append(safe)

    if file2 is not None:
        with open(file2, "r") as file_2:  # train_file
            for line in file_2:
                item = json.loads(line)
                safe = item["safe"]
                block_activations = item['block_activations']
                for layer_num in range(0, 32):
                    layer_activations = block_activations[str(layer_num)][0]
                    for head_num in range(len(layer_activations)):
                        res[f"layer_{layer_num}_head_{head_num}"]['activations'].append(layer_activations[head_num])
                        res[f"layer_{layer_num}_head_{head_num}"]['labels'].append(safe)
    return res




if __name__ == "__main__":
    # case 1
    # train_file1 = 'playground/data/lmalpaca/llava-v1.5-7b_lmalpaca_head_activations_without_image_new.json'
    # train_file2 = 'playground/data/xstest/llava-v1.5-7b_xstest_head_activations_without_image.json'
    #
    # # test_file = "playground/data/safebench_alpaca/llava-v1.5-7b_safebench_alpaca_head_activations_without_image_new.json"
    # # out_file = "result/safebench_alpaca/llava_v1.5_7b_probe_layer_head_new.json"
    #
    # test_file = "playground/data/safebench_vlguard/llava-v1.5-7b_safebench_vlguard_head_activations_with_image.json"
    # out_file = "result/safebench_vlguard/llava_v1.5_7b_probe_layer_head_new.json"

    # case 2

    train_file1 = "playground/data/safebench_alpaca/llava-v1.5-7b_safebench_alpaca_head_activations_without_image_new.json"
    train_file2 = 'playground/data/xstest/llava-v1.5-7b_xstest_head_activations_without_image.json'

    # test_file = 'playground/data/lmalpaca/llava-v1.5-7b_lmalpaca_head_activations_without_image_new.json'
    # out_file = "result/lmalpaca/llava_v1.5_7b_probe_layer_head_on_safebenalpacaxtest.json"

    test_file = "playground/data/safebench_vlguard/llava-v1.5-7b_safebench_vlguard_head_activations_with_image.json"
    out_file = "result/safebench_vlguard/llava_v1.5_7b_probe_layer_head_on_safebenalpacaxtest.json"

    # case 3
    # test_file = "playground/data/vlguard/llava-v1.5-7b_test_vlguard_head_activations_with_image.json"
    # out_file = "result/vlguard/llava_v1.5_7b_probe_layer_head_on_safebenalpacaxtest.json"

    train_res = generate_data(train_file1, train_file2)
    test_res = generate_data(test_file)


    out_file_path = os.path.expanduser(out_file)
    if os.path.exists(out_file_path):
        os.remove(out_file_path)

    with open(out_file_path, 'w') as out_file:
        for layer_num in range(0, 32):  # 0, 32
            for head_num in range(0, 32):  # 0, 32
                train_layer_head_data = train_res[f"layer_{layer_num}_head_{head_num}"]
                train_activations = train_layer_head_data['activations']
                train_labels = train_layer_head_data['labels']
                test_layer_head_data = test_res[f"layer_{layer_num}_head_{head_num}"]
                test_activations = test_layer_head_data['activations']
                test_labels = test_layer_head_data['labels']
                train_dataset = CustomDataset(train_activations, train_labels)
                test_dataset = CustomDataset(test_activations, test_labels)

                # 创建 DataLoader
                train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
                test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)

                input_dim = 128  # Example dimension
                set_random_seed(42)
                model = Probe(input_dim).to(device)
                criterion = nn.BCELoss()
                optimizer = optim.Adam(model.parameters())

                # # Train the model
                num_epochs = 3
                best_accuracy, best_precision, best_recall, best_f1, best_pr_auc, count, train_count = train(model, criterion
                                                                                                             , optimizer
                                                                                                             , train_loader
                                                                                                             , test_loader
                                                                                                             , num_epochs
                                                                                                             , device)
                json.dump({"id": f"layer_{layer_num}_head_{head_num}", "best_accuracy": best_accuracy,
                           "best_precision": best_precision,
                           "best_recall": best_recall, "best_f1": best_f1, "best_pr_auc": best_pr_auc, "count": count,
                           "train_count": train_count}, out_file)
                out_file.write('\n')


