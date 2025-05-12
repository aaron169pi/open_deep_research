from pydantic import BaseModel
from typing import List


class FileGeneration(BaseModel):
    file_path: str
    content: str
    summary: str


class FileGenerationList(BaseModel):
    items: List[FileGeneration]


class FileChanges(BaseModel):
    file_path: str
    changes: str


class FileChangesList(BaseModel):
    items: List[FileChanges]


class FileStructureList(BaseModel):
    paths: List[str]
