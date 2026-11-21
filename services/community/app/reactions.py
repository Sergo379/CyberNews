from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from .schemas import ReactionView


def tallies(db, model, targets, user_id):
    own = func.max(case((model.user_id == user_id, model.reaction))).label("own")
    query = select(
        model.target_id,
        func.count().filter(model.reaction == "like").label("likes"),
        func.count().filter(model.reaction == "dislike").label("dislikes"),
        own,
    ).where(model.target_id.in_(targets)).group_by(model.target_id)
    return {row.target_id: ReactionView(likes=row.likes, dislikes=row.dislikes, my_reaction=row.own)
            for row in db.execute(query)}


def tally(db, model, target_id, user_id):
    return tallies(db, model, [target_id], user_id).get(target_id, ReactionView())


def set_reaction(db, model, target_id, user_id, reaction):
    statement = insert(model).values(target_id=target_id, user_id=user_id, reaction=reaction)
    db.execute(statement.on_conflict_do_update(
        index_elements=[model.target_id, model.user_id],
        set_={"reaction": statement.excluded.reaction},
        where=model.reaction != statement.excluded.reaction,
    ))
