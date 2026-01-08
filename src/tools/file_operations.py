import os
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

class FileOperations:
    """
    Outils sécurisés pour la manipulation de fichiers
    """
    
    @staticmethod
    def get_python_files(directory: str) -> List[str]:
        """Récupère tous les fichiers Python d'un dossier
        
        Args:
            directory: Chemin du répertoire à scanner
            
        Returns:
            List[str]: Liste des chemins de fichiers .py trouvés
        """
        python_files = []
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
        return python_files
    
    @staticmethod
    def read_file(file_path: str) -> str:
        """Lit le contenu d'un fichier de manière sécurisée
        
        Args:
            file_path: Chemin du fichier à lire
            
        Returns:
            str: Contenu du fichier
            
        Raises:
            FileNotFoundError: Si le fichier n'existe pas
            UnicodeDecodeError: Si l'encodage est incorrect
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Fichier introuvable: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    @staticmethod
    def write_file(file_path: str, content: str) -> None:
        """Écrit du contenu dans un fichier (sécurisé - sandbox uniquement)
        
        Args:
            file_path: Chemin du fichier de destination
            content: Contenu à écrire
            
        Raises:
            PermissionError: Si tentative d'écriture hors sandbox
        """
        # Vérification: écriture uniquement dans sandbox
        abs_path = os.path.abspath(file_path)
        if 'sandbox' not in abs_path and 'test' not in abs_path:
            raise PermissionError(f"❌ Écriture interdite hors de sandbox: {file_path}")
        
        # Créer le répertoire parent si nécessaire
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

class SafetyValidator:
    """
    Validations de sécurité pour éviter les opérations dangereuses
    """
    
    @staticmethod
    def is_safe_path(file_path: str, allowed_dirs: List[str] = None) -> bool:
        """Vérifie si un chemin est sûr pour les opérations
        
        Args:
            file_path: Chemin à vérifier
            allowed_dirs: Liste des répertoires autorisés (défaut: ['sandbox', 'test'])
            
        Returns:
            bool: True si le chemin est sûr
        """
        if allowed_dirs is None:
            allowed_dirs = ['sandbox', 'test']
        
        abs_path = os.path.abspath(file_path)
        
        # Vérifier que le chemin contient un des répertoires autorisés
        return any(allowed_dir in abs_path for allowed_dir in allowed_dirs)
    
    @staticmethod
    def validate_python_code(code: str) -> Dict:
        """Vérifie que le code ne contient pas d'opérations dangereuses
        
        Args:
            code: Code Python à valider
            
        Returns:
            Dict: {
                'safe': bool,
                'warnings': List[str]
            }
        """
        warnings = []
        
        # Liste noire de mots-clés dangereux
        dangerous_patterns = [
            ('os.system', 'Exécution de commandes système'),
            ('subprocess.call', 'Exécution de sous-processus non contrôlée'),
            ('eval(', 'Utilisation de eval()'),
            ('exec(', 'Utilisation de exec()'),
            ('__import__', 'Import dynamique suspect'),
            ('open(', 'Opération fichier non contrôlée'),
            ('rmtree', 'Suppression récursive dangereuse'),
        ]
        
        for pattern, description in dangerous_patterns:
            if pattern in code:
                warnings.append(f"⚠️ {description}: '{pattern}' détecté")
        
        return {
            'safe': len(warnings) == 0,
            'warnings': warnings
        }