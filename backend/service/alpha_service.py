from typing import List, Optional, Dict, Any
from fastapi import HTTPException
from utils.alpha_calculator import validate_formula
from storage.db import Database

class AlphaService:
    def __init__(self, db: Database):
        self.db = db

    async def create_alpha(self, alpha: str) -> Dict[str, Any]:
        # Validate formula before saving
        try:
            validate_formula(alpha)
        except (SyntaxError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid formula: {e}")
        try:
            alpha_id = await self.db.create_alpha(alpha)
            return await self.get_alpha(alpha_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def get_alpha(self, alpha_id: int) -> Dict[str, Any]:
        alpha = await self.db.get_alpha(alpha_id)
        if not alpha:
            raise HTTPException(status_code=404, detail="Alpha not found")
        return alpha

    async def get_all_alphas(self) -> List[Dict[str, Any]]:
        try:
            return await self.db.get_all_alphas()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    async def update_alpha(self, alpha_id: int, alpha: str) -> Dict[str, Any]:
        # Validate formula before updating
        try:
            validate_formula(alpha)
        except (SyntaxError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid formula: {e}")
        success = await self.db.update_alpha(alpha_id, alpha)
        if not success:
            raise HTTPException(status_code=404, detail="Alpha not found")
        return await self.get_alpha(alpha_id)

    async def delete_alpha(self, alpha_id: int) -> Dict[str, Any]:
        alpha = await self.get_alpha(alpha_id)
        success = await self.db.delete_alpha(alpha_id)
        if not success:
            raise HTTPException(status_code=404, detail="Alpha not found")
        return alpha
