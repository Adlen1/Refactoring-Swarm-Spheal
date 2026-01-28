import os
from typing import Dict, List
from mistralai import Mistral
from src.utils.logger import log_experiment, ActionType
from src.tools.file_operations import FileOperations

class FixerAgent:
    """Agent Fixer - Takes Auditor results and applies code corrections"""
    
    def __init__(self, model_name: str = "mistral-large-latest"):
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("❌ MISTRAL_API_KEY non trouvée")
        
        self.client = Mistral(api_key=api_key)
        self.model_name = model_name
        self.name = "Fixer"

    def apply_fixes(self, file_path: str, audit_results: Dict) -> Dict:
        """Reads a file and applies the suggested fixes using the LLM"""
        
        if not audit_results.get("issues"):
            print(f"Aucun problème à corriger pour {file_path}")
            return "1"

        original_content = FileOperations.read_file(file_path)
        
        # Build the prompt for the Fixer
        prompt = self._build_fixer_prompt(file_path, original_content, audit_results)
        
        try:
            print(f"Réparation de {file_path} en cours...")
            response = self.client.chat.complete(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}]
            )

            raw_response = response.choices[0].message.content
            fixed_code = self._extract_code(response.choices[0].message.content)
            

            if not fixed_code.strip():
                raise ValueError("Le LLM a généré un code vide")
            
           
            FileOperations.write_file(file_path, fixed_code)
            
            log_experiment(
               agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.FIX,  # This action requires strict logging
                details={
                    "input_prompt": prompt,          
                    "output_response": raw_response, 
                    "file": file_path,
                    "fixes_applied": len(audit_results['issues'])
                },
                status="SUCCESS"
            )
            return fixed_code
            
        except Exception as e:
            print(f"Échec de la réparation: {e}")
            log_experiment(
                    agent_name=self.name,
                    model_used=self.model_name,
                    action=ActionType.FIX,
                    details={
                        "input_prompt": prompt,
                        "output_response": str(e), # Log the error as the response
                        "file": file_path,
                        "error": str(e)
                    },
                    status="FAILURE"
                )
            return "0"

    def _build_fixer_prompt(self, file_path: str, content: str, audit: Dict) -> str:
        issues_str = "\n".join([f"- L{i.get('line')}: {i.get('description')} (Suggestion: {i.get('suggestion')})" 
                               for i in audit.get("issues", [])])
        
        return f"""Tu es un développeur Python expert. Ta mission est de corriger le fichier suivant en respectant STRICTEMENT les suggestions de l'audit.
                   FICHIER: {file_path}

                   LISTE DES PROBLÈMES À CORRIGER:
                   {issues_str}

                   CODE SOURCE ORIGINAL:
                   ```python
                   {content}"""
    
    def _extract_code(self, response: str) -> str:
        if "```python" in response:
            return response.split("```python")[1].split("```")[0].strip()
        elif "```" in response:
            return response.split("```")[1].split("```")[0].strip()
        return response.strip()
    