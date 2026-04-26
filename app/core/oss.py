import json
import logging
from datetime import datetime

import oss2

from app.config import settings

logger = logging.getLogger(__name__)

def upload_transaction_log(transaction_data: dict) -> None:
    """
    Asynchronously uploads a transaction log to Alibaba Cloud OSS.
    Requires oss_access_key_id, oss_access_key_secret, and oss_endpoint.
    Uses fallback/mock behavior if credentials are not provided.
    """
    if not all([settings.oss_access_key_id, settings.oss_access_key_secret, settings.oss_endpoint]):
        logger.warning("Alibaba Cloud OSS credentials missing. Mocking upload of transaction log.")
        logger.info(f"[MOCK OSS UPLOAD] Bucket: {settings.oss_bucket_name} | Data: {json.dumps(transaction_data)}")
        return

    try:
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket_name)

        # Generate a unique key based on timestamp and transaction ID
        tx_id = transaction_data.get("transaction_id", "unknown_tx")
        timestamp_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        object_name = f"transactions/{timestamp_str}_{tx_id}.json"

        # Convert dictionary to JSON string
        log_json = json.dumps(transaction_data)

        # Upload
        bucket.put_object(object_name, log_json)
        logger.info(f"Successfully uploaded transaction log to OSS: {object_name}")

    except Exception as e:
        logger.error(f"Failed to upload transaction log to OSS: {e}")
