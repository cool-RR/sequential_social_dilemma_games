import math

import numpy as np
from gym.spaces import Box, Dict, Discrete

from social_dilemmas.envs.agent import SwitchAgent
from social_dilemmas.envs.map_env import ACTIONS, MapEnv
from social_dilemmas.maps import SwitchMapElements

# Add custom actions to the agent
ACTIONS["TOGGLE_SWITCH"] = 1  # length of firing range

# Custom colour dictionary
SWITCH_COLORS = {
    b"D": np.array([180, 180, 180], dtype=np.uint8),  # Grey closed door - same color as walls
    b"d": np.array([255, 255, 255], dtype=np.uint8),  # White opened door
    b"S": np.array([0, 255, 0], dtype=np.uint8),  # Green turned-on switch
    b"s": np.array([255, 0, 0], dtype=np.uint8),
}  # Red turned-off switch

GIVE_EXTERNAL_SWITCH_REWARD = int(False)

SWITCH_VIEW_SIZE = 3


class SwitchEnv(MapEnv):
    def __init__(self, args, num_agents=1, render=False, return_agent_actions=False):
        constructed_map = self.construct_map(args.num_switches)
        super().__init__(constructed_map, num_agents, render)
        self.return_agent_actions = return_agent_actions
        self.initial_map_state = dict()
        self.switch_locations = []
        self.door_locations = []
        self.switch_count = 0
        self.prev_activated_switch_count = 0
        self.view_len = SWITCH_VIEW_SIZE

        # Extra logging metrics
        self.timestep = 0
        self.total_pulled_on = 0
        self.total_pulled_off = 0
        self.timestep_first_switch_pull = np.nan
        self.timestep_last_switch_pull = np.nan
        self.switches_on_at_termination = 0
        self.total_successes = 0

        for row in range(self.base_map.shape[0]):
            for col in range(self.base_map.shape[1]):
                current_char = self.base_map[row, col]
                if current_char in [b"s", b"S", b"d", b"D"]:
                    self.initial_map_state[row, col] = current_char
                # Remember switch/door locations for faster access
                if current_char in [b"s", b"S"]:
                    self.switch_locations.append((row, col))
                    self.switch_count += 1
                if current_char in [b"d", b"D"]:
                    self.door_locations.append((row, col))

        self.color_map.update(SWITCH_COLORS)

    @staticmethod
    def construct_map(num_switches):
        # Minimum of 1 row so that the agent can be placed
        num_rows = max(1, int(math.ceil(num_switches / 2)))
        partial_map = [SwitchMapElements.top_row]
        for i in range(num_rows):
            if num_switches == 0:
                partial_map.append(SwitchMapElements.empty_row)
            elif num_switches == 1:
                partial_map.append(SwitchMapElements.one_switch_row)
                num_switches -= 1
            elif num_switches > 1:
                partial_map.append(SwitchMapElements.two_switch_row)
                num_switches -= 2
        partial_map.append(SwitchMapElements.bottom_row)
        middle_row = int(math.ceil(num_rows / 2))
        partial_map[middle_row] = partial_map[middle_row][:3] + "P" + partial_map[middle_row][4:]
        return partial_map

    def create_extra_info_dict(self):
        return {
            "switches_on_at_termination": self.switches_on_at_termination,
            "total_pulled_on": self.total_pulled_on,
            "total_pulled_off": self.total_pulled_off,
            "timestep_first_switch_pull": self.timestep_first_switch_pull,
            "timestep_last_switch_pull": self.timestep_last_switch_pull,
            "total_successes": self.total_successes,
        }

    def step(self, actions):
        observations, rewards, dones, info = super().step(actions)
        first_agent = next(iter(actions.keys()))
        if rewards[first_agent] > 0.1:
            self.total_successes += 1

        extra_info = {first_agent: self.create_extra_info_dict()}
        self.timestep += 1
        return observations, rewards, dones, {**info, **extra_info}

    @property
    def action_space(self):
        return Discrete(8)

    @property
    def observation_space(self):
        if self.return_agent_actions:
            # We will append on some extra values to represent the actions of other agents
            return Dict(
                {
                    "curr_obs": Box(
                        low=0,
                        high=255,
                        shape=(2 * self.view_len + 1, 2 * self.view_len + 1, 3),
                        dtype=np.uint8,
                    ),
                    "other_agent_actions": Box(
                        low=0, high=len(ACTIONS), shape=(self.num_agents - 1,), dtype=np.uint8,
                    ),
                    "visible_agents": Box(
                        low=0, high=self.num_agents, shape=(self.num_agents - 1,), dtype=np.uint8,
                    ),
                }
            )
        else:
            return Dict(
                {
                    "curr_obs": Box(
                        low=0,
                        high=255,
                        shape=(2 * self.view_len + 1, 2 * self.view_len + 1, 3),
                        dtype=np.uint8,
                    )
                }
            )

    def setup_agents(self):
        map_with_agents = self.get_map_with_agents()

        for i in range(self.num_agents):
            agent_id = "agent-" + str(i)
            spawn_point = self.spawn_point()
            rotation = self.spawn_rotation()
            grid = map_with_agents
            agent = SwitchAgent(agent_id, spawn_point, rotation, grid, SWITCH_VIEW_SIZE)
            self.agents[agent_id] = agent

    def custom_reset(self):
        """Initialize the switches/doors"""
        for coordinates, char in self.initial_map_state.items():
            self.world_map[coordinates[0], coordinates[1]] = char
        self.prev_activated_switch_count = 0

        # Extra logging metrics
        self.timestep = 0
        self.total_pulled_on = 0
        self.total_pulled_off = 0
        self.timestep_first_switch_pull = np.nan
        self.timestep_last_switch_pull = np.nan
        self.switches_on_at_termination = 0
        self.total_successes = 0

    def custom_action(self, agent, action):
        agent.fire_beam(b"F")
        updates = self.update_map_fire(
            agent.get_pos().tolist(),
            agent.get_orientation(),
            fire_len=ACTIONS["TOGGLE_SWITCH"],
            fire_char=b"F",
            cell_types=[b"s", b"S"],
            update_char=[b"S", b"s"],
            beam_width=1,
        )
        return updates

    def custom_map_update(self):
        activated_switch_count = 0
        for row, col in self.switch_locations:
            if self.world_map[row, col] == b"S":
                activated_switch_count += 1

        switch_difference = activated_switch_count - self.prev_activated_switch_count
        external_switch_reward = switch_difference * GIVE_EXTERNAL_SWITCH_REWARD
        self.prev_activated_switch_count = activated_switch_count

        for agent in list(self.agents.values()):
            agent.reward_this_turn += external_switch_reward

        # Open doors if all switches have been activated
        open_doors = activated_switch_count == self.switch_count
        door_char = b"d" if open_doors else b"D"
        updates = []
        for row, col in self.door_locations:
            updates.append((row, col, door_char))
        self.update_map(updates)

        # Update metrics
        if switch_difference != 0:
            self.timestep_last_switch_pull = self.timestep
            if np.isnan(self.timestep_first_switch_pull):
                self.timestep_first_switch_pull = self.timestep
            self.total_pulled_on += max(0, switch_difference)
            self.total_pulled_off += max(0, -switch_difference)
            self.switches_on_at_termination = activated_switch_count

    @staticmethod
    def count_switches(window):
        # Compute how many switches are activated
        # Testing function
        unique, counts = np.unique(window, return_counts=True)
        counts_dict = dict(zip(unique, counts))
        num_switches = counts_dict.get(b"S", 0)
        return num_switches

    @staticmethod
    def on_episode_end(info):
        episode = info["episode"]
        last_info = episode.last_info_for("agent-0")
        extra_info_keys = [
            "switches_on_at_termination",
            "total_pulled_on",
            "total_pulled_off",
            "timestep_first_switch_pull",
            "timestep_last_switch_pull",
            "total_successes",
        ]
        for key in extra_info_keys:
            episode.custom_metrics[key] = last_info[key]

    @staticmethod
    def get_environment_callbacks():
        callbacks = {"on_episode_end": SwitchEnv.on_episode_end}
        return callbacks
