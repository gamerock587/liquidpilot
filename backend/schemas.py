from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlsplit

class State(StrEnum):
    CREATED='CREATED'
    PLANNING='PLANNING'
    READY='READY'
    BROWSING='BROWSING'
    EXTRACTING='EXTRACTING'
    VERIFYING='VERIFYING'
    WAITING_FOR_APPROVAL='WAITING_FOR_APPROVAL'
    RECOVERING='RECOVERING'
    PAUSED='PAUSED'
    COMPLETED='COMPLETED'
    PARTIALLY_COMPLETED='PARTIALLY_COMPLETED'
    FAILED='FAILED'
    CANCELLED='CANCELLED'

TERMINAL = {State.COMPLETED, State.PARTIALLY_COMPLETED, State.FAILED, State.CANCELLED}

class TaskSpec(BaseModel):
    browser_mode: Literal['isolated','chrome'] = 'isolated'
    goal: str = Field(min_length=5, max_length=4000)
    workflow: Literal['auto','research','navigate','extract','form'] = 'auto'
    mode: Literal['observe','assisted','authorized'] = 'observe'
    seed_urls: list[str] = Field(default_factory=list, max_length=8)
    queries: list[str] = Field(default_factory=list, max_length=4)
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)
    allowed_actions: list[str] = Field(default_factory=lambda:['navigate','extract','scroll','wait','back'])
    source_target: int = Field(default=3, ge=1, le=8)
    max_steps: int = Field(default=18, ge=3, le=50)
    duration_minutes: int = Field(default=10, ge=1, le=30)
    fields: dict[str,str] = Field(default_factory=dict, max_length=20)
    success_text: str = Field(default='', max_length=500)
    remember_public: bool = False
    attachment_ids: list[str] = Field(default_factory=list, max_length=6)

    @field_validator('allowed_domains')
    @classmethod
    def validate_domains(cls, domains):
        result=[]
        for domain in domains:
            domain=domain.lower().strip().rstrip('.')
            if not domain or any(c in domain for c in '/:@*?#\\'):
                raise ValueError('Use exact hostnames, without URLs or wildcard domains.')
            result.append(domain.encode('idna').decode())
        return result

    @field_validator('fields')
    @classmethod
    def validate_fields(cls, fields):
        if any(len(k)>150 or len(v)>2000 for k,v in fields.items()):
            raise ValueError('Form labels or values are too long.')
        if any(any(secret in k.lower() for secret in ('password','credit card','cvv','secret','token','otp')) for k in fields):
            raise ValueError('Enter passwords and authentication codes manually in the browser.')
        return fields

class Action(BaseModel):
    id: str
    kind: Literal['navigate','click','double_click','scroll','type','clear','select','check','press','hover','switch_tab','new_tab','close_tab','back','forward','wait','inspect','extract','screenshot','download','upload','dialog','finish','retry','skip','site_search_filters','site_play']
    description: str
    target: str = ''
    value: str = ''
    url: str = ''
    snapshot_id: str = ''
    requires_approval: bool = False

class Plan(BaseModel):
    objective: str
    workflow: str
    success_criteria: list[str]
    queries: list[str]
    steps: list[str]
    source: str = 'structured workflow'
    limitations: list[str] = Field(default_factory=list)
