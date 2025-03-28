# src/storage_client.py

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

# Use try-except for Azure SDK imports
try:
    from azure.storage.blob import (
        BlobServiceClient,
        BlobClient,
        generate_blob_sas,
        BlobSasPermissions,
        ContentSettings
    )
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
except ImportError:
    logging.exception("Azure Storage Blob library not found. Please install with 'pip install azure-storage-blob'")
    raise

from . import config # Import configuration settings

logger = logging.getLogger(__name__)

def upload_blob_and_get_sas_url(
    local_file_path: str,
    connection_string: str,
    container_name: str,
    sas_expiry_days: int = 2 # How many days the download link should be valid
) -> Optional[str]:
    """
    Uploads a file to Azure Blob Storage and generates a SAS URL for read access.

    Args:
        local_file_path: The path to the local file to upload.
        connection_string: The Azure Storage account connection string.
        container_name: The name of the blob container.
        sas_expiry_days: Number of days the generated SAS URL should be valid.

    Returns:
        The SAS URL string for the uploaded blob, or None if upload/SAS generation fails.
    """
    if not local_file_path or not os.path.exists(local_file_path):
        logger.error(f"Local file path is invalid or file does not exist: {local_file_path}")
        return None
    if not connection_string:
        logger.error("Azure Storage connection string is missing.")
        return None
    if not container_name:
        logger.error("Azure Storage container name is missing.")
        return None

    blob_name = os.path.basename(local_file_path) # Use the filename as the blob name
    logger.info(f"Attempting to upload '{blob_name}' to container '{container_name}'.")

    try:
        # 1. Create BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)

        # Optional: Create container if it doesn't exist (useful for first run)
        try:
            container_client = blob_service_client.create_container(container_name)
            logger.info(f"Container '{container_name}' created.")
        except ResourceExistsError:
            logger.debug(f"Container '{container_name}' already exists.")
            container_client = blob_service_client.get_container_client(container_name)
        except Exception as ce:
            logger.error(f"Failed to create or get container '{container_name}': {ce}", exc_info=True)
            return None


        # 2. Create BlobClient
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

        # 3. Upload File
        # Determine content type for better browser handling
        content_type = "audio/mp4" if blob_name.lower().endswith(".m4a") else "application/octet-stream"
        blob_content_settings = ContentSettings(content_type=content_type)

        with open(local_file_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True, content_settings=blob_content_settings)
        logger.info(f"Successfully uploaded '{blob_name}' to container '{container_name}'.")

        # 4. Generate SAS Token and URL
        logger.info(f"Generating SAS URL for '{blob_name}' valid for {sas_expiry_days} days.")
        sas_expiry_time = datetime.now(timezone.utc) + timedelta(days=sas_expiry_days)

        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=container_name,
            blob_name=blob_name,
            account_key=blob_service_client.credential.account_key, # Get key from service client
            permission=BlobSasPermissions(read=True),
            expiry=sas_expiry_time,
        )

        # Construct the full URL
        sas_url = f"https://{blob_client.account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"
        logger.info(f"Generated SAS URL: {sas_url}")

        return sas_url

    except ResourceNotFoundError:
         logger.error(f"Resource not found during blob operation (check connection string, container name).", exc_info=True)
         return None
    except ImportError:
         # This might happen if azure-storage-blob wasn't installed correctly
         logger.critical("azure.storage.blob library seems to be missing or corrupted.")
         return None
    except Exception as e:
        logger.error(f"An error occurred during blob upload or SAS generation: {e}", exc_info=True)
        return None