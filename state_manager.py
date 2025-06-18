import pickle
import os
from typing import List, Dict, Any, Union


class StateManager:
    def __init__(self, state_file: str = "state.pkl"):
        self.state_file = state_file
        self.default_state = {
            "plan": "",
            "work_dir": "",
            "codebase": [],
            "user_requests": [],
            "structure": [],
            "generated": [],
            "summary": [],
            "feedback_done": False,
            "html": "",
            "review_done": False,
            "classification": "",
            "assets": [],
            "chat": [],
        }
        self.load_state()

    def mark_feedback_done(self):
        self.state["feedback_done"] = True
        self.save_state()

    def mark_review_done(self):
        self.state["review_done"] = True
        self.save_state()

    def is_feedback_done(self) -> bool:
        return self.state.get("feedback_done", False)

    def is_review_done(self) -> bool:
        return self.state.get("review_done", False)

    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, "rb") as f:
                loaded_state = pickle.load(f)

            self.state = {**self.default_state, **loaded_state}
        else:
            self.state = self.default_state.copy()

    def save_state(self):
        with open(self.state_file, "wb") as f:
            pickle.dump(self.state, f)

    def update_chat(self, chat: List[object]):
        self.state["chat"] = chat
        self.save_state()

    def update_plan(self, plan: str):
        self.state["plan"] = plan
        self.save_state()

    def update_html(self, plan: str):
        self.state["html"] = plan
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

    def add_assets(self, asset: Union[object, List[object]]):
        current_count = len(self.state["assets"])
        assets_to_add = asset if isinstance(asset, list) else [asset]

        for i, a in enumerate(assets_to_add, start=1):
            tag = f"image_{current_count + i}"
            a["tag"] = tag
            self.state["assets"].append(a)

        self.save_state()

    def add_classification(self, classification: str):
        self.state["classification"] = classification
        self.save_state()

    def add_work_dir(self, work_dir: str):
        self.state["work_dir"] = work_dir
        self.save_state()

    def get_chat(self) -> List[object]:
        return self.state["chat"]

    def get_classification(self) -> str:
        return self.state["classification"]

    def get_plan(self) -> str:
        return self.state["plan"]

    def get_html(self) -> str:
        return self.state["html"]

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

    def get_assets(self) -> List[object]:
        return self.state["assets"]

    def get_work_dir(self) -> str:
        return self.state["work_dir"]
