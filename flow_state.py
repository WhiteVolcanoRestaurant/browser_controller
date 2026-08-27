#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程工作流状态机：显式记录观察、决策、操作、验证和升级阶段。"""

from enum import Enum


class FlowState(str, Enum):
    BOOT = "boot"
    OBSERVE = "observe"
    DECIDE = "decide"
    ACT = "act"
    VERIFY = "verify"
    WAIT = "wait"
    VIDEO = "video"
    VLM_REASONING = "vlm_reasoning"
    HUMAN = "human"
    COMPLETE = "complete"
    ERROR = "error"


class FlowStateMachine:
    """检查明显错误的状态跳转，并输出可审计的状态记录。"""

    _ALLOWED = {
        FlowState.BOOT: {FlowState.OBSERVE, FlowState.ERROR},
        FlowState.OBSERVE: {FlowState.DECIDE, FlowState.COMPLETE, FlowState.ERROR},
        FlowState.DECIDE: {FlowState.OBSERVE, FlowState.ACT, FlowState.WAIT,
                           FlowState.VLM_REASONING, FlowState.HUMAN,
                           FlowState.COMPLETE, FlowState.ERROR},
        FlowState.ACT: {FlowState.VERIFY, FlowState.ERROR},
        FlowState.VERIFY: {FlowState.OBSERVE, FlowState.VLM_REASONING,
                           FlowState.HUMAN, FlowState.WAIT, FlowState.ERROR},
        FlowState.WAIT: {FlowState.OBSERVE, FlowState.VLM_REASONING, FlowState.HUMAN,
                         FlowState.VIDEO},
        FlowState.VIDEO: {FlowState.OBSERVE, FlowState.WAIT, FlowState.VLM_REASONING,
                          FlowState.HUMAN, FlowState.ERROR},
        FlowState.VLM_REASONING: {FlowState.ACT, FlowState.WAIT, FlowState.HUMAN,
                                  FlowState.OBSERVE, FlowState.ERROR, FlowState.VIDEO},
        FlowState.HUMAN: {FlowState.OBSERVE, FlowState.COMPLETE, FlowState.ERROR},
        FlowState.COMPLETE: {FlowState.OBSERVE},
        FlowState.ERROR: {FlowState.OBSERVE, FlowState.HUMAN},
    }

    def __init__(self):
        self.state = FlowState.BOOT

    def transition(self, next_state, reason=""):
        next_state = FlowState(next_state)
        if next_state == self.state:
            return None
        if next_state not in self._ALLOWED.get(self.state, set()):
            raise RuntimeError(
                f"非法状态跳转: {self.state.value} -> {next_state.value} ({reason})")
        previous = self.state
        self.state = next_state
        print(f"[状态] {previous.value} -> {next_state.value}"
              + (f"：{reason}" if reason else ""))
        return previous, next_state
