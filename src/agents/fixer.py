import os
import re
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
        original_line_count = len(original_content.splitlines())
        
        # Extract original function/class names for validation
        original_functions = set(re.findall(r'^def\s+(\w+)\s*\(', original_content, re.MULTILINE))
        original_classes = set(re.findall(r'^class\s+(\w+)\s*[:\(]', original_content, re.MULTILINE))
        
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
            
            # VALIDATION: Check that fixed code is not drastically smaller
            fixed_line_count = len(fixed_code.splitlines())
            if fixed_line_count < original_line_count * 0.5:
                raise ValueError(f"Code trop court: {fixed_line_count} lignes vs {original_line_count} original (>50% de perte)")
            
            # VALIDATION: Check that all original functions/classes are preserved
            fixed_functions = set(re.findall(r'^def\s+(\w+)\s*\(', fixed_code, re.MULTILINE))
            fixed_classes = set(re.findall(r'^class\s+(\w+)\s*[:\(]', fixed_code, re.MULTILINE))
            
            missing_functions = original_functions - fixed_functions
            missing_classes = original_classes - fixed_classes
            
            if missing_functions or missing_classes:
                missing = list(missing_functions) + list(missing_classes)
                raise ValueError(f"Éléments manquants dans le code corrigé: {', '.join(missing)}")
           
            FileOperations.write_file(file_path, fixed_code)
            
            log_experiment(
               agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.FIX,  # This action requires strict logging
                details={
                    "input_prompt": prompt,          
                    "output_response": raw_response, 
                    "file": file_path,
                    "fixes_applied": len(audit_results['issues']),
                    "original_lines": original_line_count,
                    "fixed_lines": fixed_line_count
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
        issues_str = "\n".join([f"- L{i.get('line', 0)}: {i.get('description', 'N/A')} (Suggestion: {i.get('suggestion', 'N/A')})" 
                               for i in audit.get("issues", [])])
        
        # Count original elements
        function_count = len(re.findall(r'^def\s+\w+\s*\(', content, re.MULTILINE))
        class_count = len(re.findall(r'^class\s+\w+\s*[:\(]', content, re.MULTILINE))
        
        return f"""Tu es un développeur Python expert. Ta mission est de corriger le fichier suivant en respectant STRICTEMENT les suggestions de l'audit.

================================================================================
FICHIER: {file_path}
STATISTIQUES: {function_count} fonctions, {class_count} classes
================================================================================

LISTE DES PROBLÈMES À CORRIGER:
{issues_str}

================================================================================
CODE SOURCE ORIGINAL:
================================================================================
```python
{content}
```

================================================================================
RÈGLES CRITIQUES - À RESPECTER ABSOLUMENT:
================================================================================

1. **CONSERVER TOUTES LES FONCTIONS ET CLASSES** - Ne supprimer AUCUNE fonction ni classe existante
2. **CORRIGER UNIQUEMENT LES PROBLÈMES LISTÉS** - Ne pas réécrire tout le code
3. **GARDER LA STRUCTURE** - Le code corrigé doit avoir toutes les {function_count} fonctions et {class_count} classes
4. **AJOUTER DES DOCSTRINGS** si demandé, mais GARDER le code fonctionnel
5. **NE PAS SIMPLIFIER** en supprimant du code - corriger les bugs sans supprimer de fonctionnalités

IMPORTANT: Retourne le fichier Python COMPLET avec TOUTES les fonctions et classes corrigées.
Le code doit être dans un bloc ```python ... ```
"""
    
    def _extract_code(self, response: str) -> str:
        if "```python" in response:
            return response.split("```python")[1].split("```")[0].strip()
        elif "```" in response:
            return response.split("```")[1].split("```")[0].strip()
        return response.strip()
    