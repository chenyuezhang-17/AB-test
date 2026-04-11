"""Tweet posting — Owner: Alexia"""

from models import PreparedReply


def post_reply(reply: PreparedReply) -> bool:
    """Post a quote repost reply to the original tweet.

    Returns True if posted successfully.
    """
    # TODO(alexia): implement with tweepy
    # - Quote repost the original tweet (reply.tweet_id)
    # - Use reply.reply_text as tweet body
    # - Include reply.lessie_url
    # - Skip if confidence < threshold
    raise NotImplementedError("Alexia: implement tweet posting")
