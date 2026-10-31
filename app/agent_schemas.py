"""Strict schemas shared by tools and final responses."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class ImageArgs(StrictModel):
    image_id:Literal['selected-image']


class ReferenceArgs(ImageArgs):
    k:int=Field(default=3,ge=1,le=3)


class SearchArgs(StrictModel):
    query:str=Field(min_length=1,max_length=300)
    k:int=Field(default=3,ge=1,le=3)

    @model_validator(mode='after')
    def nonblank(self):
        if not self.query.strip():
            raise ValueError('blank query')
        return self


class ReadArgs(StrictModel):
    evidence_ids:list[str]=Field(min_length=1,max_length=3)


class Claim(StrictModel):
    text:str=Field(min_length=1,max_length=600)
    evidence_ids:list[str]=Field(min_length=1,max_length=5)

    @model_validator(mode='after')
    def nonblank(self):
        if not self.text.strip():
            raise ValueError('blank claim')
        return self


class FinalAnswer(StrictModel):
    status:Literal['answered','insufficient_evidence','needs_context']
    claims:list[Claim]=Field(max_length=5)
    limitations:list[str]=Field(default_factory=list,max_length=6)
    follow_up_question:str|None=Field(default=None,max_length=500)

    @model_validator(mode='after')
    def required_fields(self):
        if self.status=='answered' and not self.claims:
            raise ValueError('answered requires cited claims')
        if self.status=='needs_context' and not self.follow_up_question:
            raise ValueError('needs_context requires a follow-up question')
        if self.status=='insufficient_evidence' and not self.limitations:
            raise ValueError('insufficient evidence requires limitations')
        return self


SCHEMAS={'analyze_image':ImageArgs,'search_reference_images':ReferenceArgs,
         'search_documents':SearchArgs,'read_evidence':ReadArgs,'submit_answer':FinalAnswer}
DESCRIPTIONS={
    'analyze_image':'本機分析已由使用者選取的圖片，取得分數、門檻與熱圖，沒有圖片時會回傳缺圖狀態。',
    'search_reference_images':'搜尋最多三張正常參考圖片，結果只代表外觀相近。',
    'search_documents':'搜尋最多三段文件全文與來源，回傳 evidence_id 後可在結論引用。',
    'read_evidence':'補讀本輪搜尋回傳的 doc: 開頭 evidence_ids，搜尋已回傳全文時可省略。',
    'submit_answer':'提交最終結果，每項 claims 都需本輪有效 evidence_ids，資料不足或缺圖片需標明。',
}


def tool_definitions():
    return [{'type':'function','function':{'name':name,'description':DESCRIPTIONS[name],
              'parameters':schema.model_json_schema()}} for name,schema in SCHEMAS.items()]
