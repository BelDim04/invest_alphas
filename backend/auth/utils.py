from auth.db import UserDB
from auth.models import UserCreate
from storage.db import db
import logging

logger = logging.getLogger(__name__)

async def create_initial_admin():
    """Create initial admin user if it doesn't exist"""
    try:
        # Create user DB
        user_db = UserDB(db)
        
        # Initialize tables
        await user_db.init_tables()
        
        # Check if admin user exists
        admin = await user_db.get_user_by_username("admin")
        if not admin:
            logger.info("Creating initial admin user")
            admin_user = UserCreate(
                username="admin",
                email="admin@example.com",
                full_name="System Administrator",
                password="admin123",  # This should be changed immediately after first login
                tinkoff_token=None  # Admin needs to set their own token
            )
            await user_db.create_user(admin_user)
            logger.info("Admin user created successfully")
        else:
            logger.info("Admin user already exists")
            
    except Exception as e:
        logger.error(f"Error creating admin user: {str(e)}")
        raise 