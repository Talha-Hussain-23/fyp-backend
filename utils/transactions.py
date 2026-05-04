"""
MongoDB Transaction Utilities
Provides safe transaction wrappers for multi-step operations
"""
from contextlib import contextmanager
from pymongo import ReadConcern, WriteConcern, ReadPreference
from pymongo.errors import PyMongoError
from fastapi import HTTPException
from core.logging_service import logger


@contextmanager
def atomic_transaction(db):
    """
    Context manager for MongoDB transactions with automatic rollback
    
    Usage:
        with atomic_transaction(db) as session:
            db.collection1.update_one(..., session=session)
            db.collection2.insert_one(..., session=session)
            # Automatically commits if no exception
            # Automatically rolls back if exception occurs
    """
    client = db.client
    session = client.start_session()
    
    try:
        with session.start_transaction(
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern("majority", j=True),
            read_preference=ReadPreference.PRIMARY
        ):
            yield session
            session.commit_transaction()
            logger.info("Transaction committed successfully")
    except PyMongoError as e:
        # ✅ FIX: Only abort if transaction is still active
        try:
            if session.in_transaction:
                session.abort_transaction()
                logger.warning("Transaction aborted due to MongoDB error")
        except Exception as abort_error:
            logger.error(f"Error during transaction abort: {abort_error}")
        
        logger.error(f"MongoDB transaction error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Database transaction failed: {str(e)}"
        )
    except Exception as e:
        # ✅ FIX: Only abort if transaction is still active
        try:
            if session.in_transaction:
                session.abort_transaction()
                logger.warning("Transaction aborted due to error")
        except Exception as abort_error:
            logger.error(f"Error during transaction abort: {abort_error}")
        
        logger.error(f"Transaction error: {e}")
        raise
    finally:
        session.end_session()


def safe_multi_step_operation(db, operations: list):
    """
    Execute multiple database operations in a single transaction
    
    Args:
        db: MongoDB database instance
        operations: List of tuples (collection_name, operation_type, filter, update/document)
        
    Example:
        operations = [
            ('interviews', 'update_one', {'_id': interview_id}, {'$set': {'status': 'completed'}}),
            ('applications', 'update_one', {'_id': app_id}, {'$set': {'interview_score': 85}}),
            ('jds', 'update_one', {'_id': job_id}, {'$inc': {'completed_interviews': 1}})
        ]
        safe_multi_step_operation(db, operations)
    """
    with atomic_transaction(db) as session:
        for collection_name, op_type, filter_doc, update_doc in operations:
            collection = db[collection_name]
            
            if op_type == 'update_one':
                collection.update_one(filter_doc, update_doc, session=session)
            elif op_type == 'update_many':
                collection.update_many(filter_doc, update_doc, session=session)
            elif op_type == 'insert_one':
                collection.insert_one(update_doc, session=session)
            elif op_type == 'delete_one':
                collection.delete_one(filter_doc, session=session)
            else:
                raise ValueError(f"Unsupported operation type: {op_type}")
