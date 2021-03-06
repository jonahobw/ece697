import random
import numpy as np

from .MCTS import Node, MCTS, Edge


from .config import *
import time

import matplotlib.pyplot as plt
from IPython import display
import pylab as pl


class User():
    def __init__(self, name, state_size, action_size):
        self.name = name
        self.state_size = state_size
        self.action_size = action_size

    def act(self, state, tau):
        action = -1
        mapping = {}
        for action in state._allowedActions():
            mapping[(action % 7) + 1] = action
        allowed = sorted(list(mapping.keys()))
        print(f"Allowed actions: {allowed}")
        while action not in allowed:
            action = int(input('Enter your chosen action: '))
        action = mapping[action]
        pi = np.zeros(self.action_size)
        pi[action] = 1
        value = 0
        NN_value = 0
        return (action, pi, value, NN_value)


class Agent():
    def __init__(self, name, state_size, action_size, mcts_simulations, cpuct, model):
        self.name = name

        self.state_size = state_size
        self.action_size = action_size

        self.cpuct = cpuct

        self.MCTSsimulations = mcts_simulations
        self.model = model

        self.mcts = None

        self.train_overall_loss = []
        self.train_value_loss = []
        self.train_policy_loss = []
        self.val_overall_loss = []
        self.val_value_loss = []
        self.val_policy_loss = []

    def simulate(self):

        print('ROOT NODE...%s', self.mcts.root.state.id)
        # self.mcts.root.state.render(lg.logger_mcts)
        print('CURRENT PLAYER...%d', self.mcts.root.state.playerTurn)

        ##### MOVE THE LEAF NODE
        leaf, value, done, breadcrumbs = self.mcts.moveToLeaf()
        # leaf.state.render(lg.logger_mcts)

        ##### EVALUATE THE LEAF NODE
        value, breadcrumbs = self.evaluateLeaf(leaf, value, done, breadcrumbs)

        ##### BACKFILL THE VALUE THROUGH THE TREE
        self.mcts.backFill(leaf, value, breadcrumbs)

    def act(self, state, tau):

        if self.mcts == None or state.id not in self.mcts.tree:
            self.buildMCTS(state)
        else:
            self.changeRootMCTS(state)

        #### run the simulation
        for sim in range(self.MCTSsimulations):
            print('***************************')
            print('****** SIMULATION %d ******', sim + 1)
            print('***************************')
            self.simulate()

        #### get action values
        pi, values = self.getAV(1)

        ####pick the action
        action, value = self.chooseAction(pi, values, tau)

        nextState, _, _ = state.takeAction(action)

        NN_value = -self.get_preds(nextState)[0]

        print('ACTION VALUES...%s', pi)
        print('CHOSEN ACTION...%d', action)
        print('MCTS PERCEIVED VALUE...%f', value)
        print('NN PERCEIVED VALUE...%f', NN_value)

        return (action, pi, value, NN_value)

    def get_preds(self, state):
        # predict the leaf
        inputToModel = np.array([self.model.convertToModelInput(state)])

        preds = self.model.predict(inputToModel)
        value_array = preds[0]
        logits_array = preds[1]
        value = value_array[0]

        logits = logits_array[0]

        allowedActions = state.allowedActions

        mask = np.ones(logits.shape, dtype=bool)
        mask[allowedActions] = False
        logits[mask] = -100

        # SOFTMAX
        odds = np.exp(logits)
        probs = odds / np.sum(odds)  ###put this just before the for?

        return ((value, probs, allowedActions))

    def evaluateLeaf(self, leaf, value, done, breadcrumbs):

        print('------EVALUATING LEAF------')

        if done == 0:

            value, probs, allowedActions = self.get_preds(leaf.state)
            print('PREDICTED VALUE FOR %d: %f', leaf.state.playerTurn, value)

            probs = probs[allowedActions]

            for idx, action in enumerate(allowedActions):
                newState, _, _ = leaf.state.takeAction(action)
                if newState.id not in self.mcts.tree:
                    node = Node(newState)
                    self.mcts.addNode(node)
                    print('added node...%s...p = %f', node.id, probs[idx])
                else:
                    node = self.mcts.tree[newState.id]
                    print('existing node...%s...', node.id)

                newEdge = Edge(leaf, node, probs[idx], action)
                leaf.edges.append((action, newEdge))

        else:
            print('GAME VALUE FOR %d: %f', leaf.playerTurn, value)

        return ((value, breadcrumbs))

    def getAV(self, tau):
        edges = self.mcts.root.edges
        pi = np.zeros(self.action_size, dtype=np.integer)
        values = np.zeros(self.action_size, dtype=np.float32)

        for action, edge in edges:
            pi[action] = pow(edge.stats['N'], 1 / tau)
            values[action] = edge.stats['Q']

        pi = pi / (np.sum(pi) * 1.0)
        return pi, values

    def chooseAction(self, pi, values, tau):
        if tau == 0:
            actions = np.argwhere(pi == max(pi))
            action = random.choice(actions)[0]
        else:
            action_idx = np.random.multinomial(1, pi)
            action = np.where(action_idx == 1)[0][0]

        value = values[action]

        return action, value

    def replay(self, ltmemory):
        print('******RETRAINING MODEL******')

        for i in range(TRAINING_LOOPS):
            minibatch = random.sample(ltmemory, min(BATCH_SIZE, len(ltmemory)))

            training_states = np.array([self.model.convertToModelInput(row['state']) for row in minibatch])
            training_targets = {'value_head': np.array([row['value'] for row in minibatch])
                , 'policy_head': np.array([row['AV'] for row in minibatch])}

            fit = self.model.fit(training_states, training_targets, epochs=EPOCHS, verbose=1, validation_split=0,
                                 batch_size=32)
            print('NEW LOSS %s', fit.history)

            self.train_overall_loss.append(round(fit.history['loss'][EPOCHS - 1], 4))
            self.train_value_loss.append(round(fit.history['value_head_loss'][EPOCHS - 1], 4))
            self.train_policy_loss.append(round(fit.history['policy_head_loss'][EPOCHS - 1], 4))

        plt.plot(self.train_overall_loss, 'k')
        plt.plot(self.train_value_loss, 'k:')
        plt.plot(self.train_policy_loss, 'k--')

        plt.legend(['train_overall_loss', 'train_value_loss', 'train_policy_loss'], loc='lower left')

        display.clear_output(wait=True)
        display.display(pl.gcf())
        pl.gcf().clear()
        time.sleep(1.0)

        print('\n')
        self.model.printWeightAverages()

    def predict(self, inputToModel):
        preds = self.model.predict(inputToModel)
        return preds

    def buildMCTS(self, state):
        print('****** BUILDING NEW MCTS TREE FOR AGENT %s ******', self.name)
        self.root = Node(state)
        self.mcts = MCTS(self.root, self.cpuct)

    def changeRootMCTS(self, state):
        print('****** CHANGING ROOT OF MCTS TREE TO %s FOR AGENT %s ******', state.id, self.name)
        self.mcts.root = self.mcts.tree[state.id]


