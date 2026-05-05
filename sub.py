import subprocess
import os
from concurrent.futures import ThreadPoolExecutor

# Dossier de travail
working_directory = r"E:\reactav\back"
base_audio_dir = os.path.abspath("../front/public/audios")

# Liste des fichiers MP3 à traiter
mp3_files = [
    os.path.join(base_audio_dir, "aro.mp3"),
    # os.path.join(base_audio_dir, "bob.mp3"),
]

# Fonction de traitement pour un seul fichier
def process_audio(mp3_file):
    try:
        # Déterminer les chemins de sortie
        base_name = os.path.splitext(os.path.basename(mp3_file))[0]
        ogg_file = os.path.join(base_audio_dir, f"{base_name}.ogg")
        json_file = os.path.join(base_audio_dir, f"{base_name}.json")

        # 1. Conversion MP3 -> OGG Vorbis
        print(f"Conversion en OGG Vorbis : {mp3_file}")
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_file, "-c:a", "libvorbis", ogg_file],
            check=True
        )

        # 2. Génération JSON avec Rhubarb
        print(f"Génération JSON avec Rhubarb pour : {ogg_file}")
        command = ["rhubarb.exe", "-f", "json", ogg_file, "-o", json_file]

        subprocess.run(command, cwd=working_directory, check=True)

        print(f"Traitement terminé : {json_file}")
        return json_file

    except subprocess.CalledProcessError as e:
        print(f"Erreur pour {mp3_file} : {e}")
        return None

# Traitement parallèle avec ThreadPoolExecutor
if __name__ == "__main__":
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(process_audio, mp3_files))

    print("Tous les fichiers ont été traités :", results)
