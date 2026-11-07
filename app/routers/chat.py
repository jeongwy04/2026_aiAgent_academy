from fastapi import APIRouter, Depends

from app.dependencies import CurrentMember, ReadSession, chat_limit
from app.schemas import ChatInput, ChatOut
from app.services.chat_service import answer_question

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatOut, dependencies=[Depends(chat_limit)])
def chat(body: ChatInput, user: CurrentMember, session: ReadSession):
    return answer_question(session, user.id, body)
