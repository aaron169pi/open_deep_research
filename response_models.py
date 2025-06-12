from pydantic import BaseModel
from typing import List


class AppTypeResponse(BaseModel):
    app_type: str


class FileGeneration(BaseModel):
    file_path: str
    content: str
    summary: str


class FileGenerationList(BaseModel):
    items: List[FileGeneration]
    reasoning: str


class FileChanges(BaseModel):
    file_path: str
    changes: str


class FileChangesList(BaseModel):
    items: List[FileChanges]
    reasoning: str


class FileStructureList(BaseModel):
    paths: List[str]


class ReviewerResponse(BaseModel):
    status_code: int
    report: str
