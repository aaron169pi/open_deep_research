import pickle
import os
from typing import List, Dict, Any


class StateManager:
    def __init__(self, state_file: str = "state.pkl"):
        self.state_file = state_file
        self.state = {
            "plan": "",
            "work_dir": "",
            "codebase": [],
            "user_requests": [],
            "structure": [],
            "generated": [],
            "summary": [],
        }
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, "rb") as f:
                self.state = pickle.load(f)

    def save_state(self):
        with open(self.state_file, "wb") as f:
            pickle.dump(self.state, f)

    def update_plan(self, plan: str):
        self.state["plan"] = plan
        self.save_state()

    def update_codebase(self, files: List[Dict[str, Any]]):
        self.state["codebase"] = files
        self.save_state()

    def update_generated(self, files: List[str]):
        self.state["generated"] = files
        self.save_state()

    def update_summary(self, files: List[str]):
        self.state["summary"] = files
        self.save_state()

    def update_structure(self, files: List[str]):
        self.state["structure"] = files
        self.save_state()

    def add_user_request(self, request: str):
        self.state["user_requests"].append(request)
        self.save_state()

    def add_work_dir(self, work_dir: str):
        self.state["work_dir"] = work_dir
        self.save_state()

    def get_plan(self) -> str:
        return self.state["plan"]

    def get_codebase(self) -> List[Dict[str, Any]]:
        return self.state["codebase"]

    def get_structure(self) -> List[str]:
        return self.state["structure"]

    def get_generated(self) -> List[str]:
        return self.state["generated"]

    def get_summary(self) -> List[str]:
        return self.state["summary"]

    def get_user_requests(self) -> List[str]:
        return self.state["user_requests"]

    def get_work_dir(self) -> str:
        return self.state["work_dir"]
