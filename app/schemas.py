from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class Field(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str | None
    status: Literal['found', 'inferred', 'uncertain', 'missing']
    evidence: str | None
    explanation: str

    @model_validator(mode='after')
    def consistent_missing(self):
        if self.value is None or not self.value.strip():
            self.value = None
            self.status = 'missing'
        elif self.status == 'missing':
            raise ValueError('A missing field cannot contain a value.')
        return self


class Agreement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_type: str
    summary: str
    currency: str | None
    agreement_value: Field
    agreement_start_date: Field
    agreement_end_date: Field
    renewal_notice_days: Field
    party_one: Field
    party_two: Field
    warnings: list[str]


FIELDS = {
    'agreement_value': 'Aggrement Value',
    'agreement_start_date': 'Aggrement Start Date',
    'agreement_end_date': 'Aggrement End Date',
    'renewal_notice_days': 'Renewal Notice (Days)',
    'party_one': 'Party One',
    'party_two': 'Party Two',
}
