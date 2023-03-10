import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical
from itertools import count
from collections import deque
import random
from tensorboardX import SummaryWriter
import gym
import numpy as np
import matplotlib.pyplot as plt

device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

class Memory(object):
    def __init__(self, memory_size: int) -> None:
        self.memory_size = memory_size
        self.buffer = deque(maxlen=self.memory_size)

    def add(self, experience) -> None:
        self.buffer.append(experience)

    def size(self):
        return len(self.buffer)

    def sample(self, batch_size: int, continuous: bool = True):
        if batch_size > self.size():
            batch_size = self.size()
        if continuous:
            rand = random.randint(0, self.size() - batch_size)
            return [self.buffer[i] for i in range(rand, rand + batch_size)]
        else:
            indexes = np.random.choice(np.arange(self.size()), size=batch_size, replace=False)
            return [self.buffer[i] for i in indexes]

    def clear(self) -> None:
        self.buffer.clear()

class SoftQNetwork(nn.Module):
    def __init__(self):
        super(SoftQNetwork, self).__init__()
        self.alpha = 4
        self.fc1 = nn.Linear(4, 64)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(64, 256)
        self.fc3 = nn.Linear(256, 2)

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        x = self.relu(x)
        x = self.fc3(x)
        return x

    # Soft-Q Value - Convert Q values of state to log probability values (i.e. log softmax)
    def getV(self, q_value):
        v = self.alpha * torch.log(torch.sum(torch.exp(q_value / self.alpha), dim=1, keepdim=True))
        return v

    def choose_action(self, state):
        state = torch.FloatTensor(state).unsqueeze(0).to(device)
        
        with torch.no_grad():
            q = self.forward(state)
            v = self.getV(q).squeeze()
            dist = torch.exp((q-v) / self.alpha)
            dist = dist / torch.sum(dist)
            c = Categorical(dist)
            a = c.sample()

        return a.item()

# Main ------------------------------------------------------------------------
env = gym.make('CartPole-v1', render_mode="rgb_array")
onlineQNetwork = SoftQNetwork().to(device)
targetQNetwork = SoftQNetwork().to(device)
targetQNetwork.load_state_dict(onlineQNetwork.state_dict())

optimizer = torch.optim.Adam(onlineQNetwork.parameters(), lr=1e-4)

gamma = 0.99
replay_memory = 50000
batch_size = 16
update_steps = 4

memory_replay = Memory(replay_memory)
writer = SummaryWriter('logs/sql')

learn_steps = 0
begin_learn = False
episode_reward = 0

averages = []

for epoch in range(500):
    state = env.reset()

    #if epoch == 0:
    state = state[0]

    episode_reward = 0
    #print("Epoch: ", epoch, "/", count())
    for time_steps in range(200):
        #print("Step: ", time_steps+1, "/", 200)
        action = onlineQNetwork.choose_action(state)
        next_state, reward, done, trunc, info = env.step(action)
        episode_reward += reward
        memory_replay.add((state, next_state, action, reward, done))

        if memory_replay.size() > 128:
            
            if begin_learn is False:
                print('Beginning to learn...')
                begin_learn = True
            learn_steps += 1
            
            if learn_steps % update_steps == 0:
                targetQNetwork.load_state_dict(onlineQNetwork.state_dict())
            batch = memory_replay.sample(batch_size, False)
            batch_state, batch_next_state, batch_action, batch_reward, batch_done = zip(*batch)

            batch_state = torch.FloatTensor(batch_state).to(device)
            batch_next_state = torch.FloatTensor(batch_next_state).to(device)
            batch_action = torch.FloatTensor(batch_action).unsqueeze(1).to(device)
            batch_reward = torch.FloatTensor(batch_reward).unsqueeze(1).to(device)
            batch_done = torch.FloatTensor(batch_done).unsqueeze(1).to(device)

            with torch.no_grad():
                next_q = targetQNetwork(batch_next_state)
                next_v = targetQNetwork.getV(next_q)
                y = batch_reward + (1 - batch_done) * gamma * next_v

            loss = F.mse_loss(onlineQNetwork(batch_state).gather(1, batch_action.long()), y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            writer.add_scalar('loss', loss.item(), global_step=learn_steps)

        if done:
            break

        state = next_state
    
    writer.add_scalar('episode reward', episode_reward, global_step=epoch)
    if epoch % 10 == 0:
        torch.save(onlineQNetwork.state_dict(), 'sql-policy.para')
        print('Ep {}\tMoving average score: {:.2f}\t'.format(epoch, episode_reward))
        averages.append(episode_reward)

plt.plot(averages)
plt.show()