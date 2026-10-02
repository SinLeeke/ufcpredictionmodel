"""Identidades compartidas entre casas de apuestas, UFCStats y CSV históricos.

Solo se unen variantes verificadas del mismo peleador. Un apellido parecido o
un primer resultado del buscador no bastan: pueden pertenecer a un homónimo.
"""
from __future__ import annotations

import re
import unicodedata


_SPECIAL = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ß": "ss",
    "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ı": "i",
})


def normalize_name(name: str) -> str:
    value = unicodedata.normalize("NFKD", str(name).translate(_SPECIAL))
    value = value.encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", "", value).split())


# Cada equivalencia está respaldada por la ficha UFC o por la misma pelea
# (fecha + rival + URL UFCStats) en ambos datasets. Evidencias y casos excluidos:
# docs/auditoria-identidades.md. No se generan aliases por similitud de texto.
# El primero es el nombre de referencia de la ficha/dataset UFCStats auditado.
_GROUPS = (
    ("King Green", "Bobby Green"),
    ("Ian Machado Garry", "Ian Garry"),
    # UFC /athlete/wang-cong y UFCStats /fighter-details/2997e7fe3c9d3d4a;
    # Betano invierte el orden del nombre en la misma pareja Silva–Wang.
    ("Wang Cong", "Cong Wang"),
    ("JunYong Park", "Jun Yong Park"),
    ("Alexander Volkov", "Alekander Volkov"),
    ("Alex Ricci", "Alessandro Ricci"),
    ("Alexander Munoz", "Alex Munoz"),
    ("Aleksandra Albu", "Alexandra Albu"),
    ("Ali AlQaisi", "Ali Qaisi"),
    ("Alvaro Herrera Mendoza", "Alvaro Herrera"),
    ("Anying Wang", "An Ying Wang"),
    ("Aoriqileng", "Aori Qileng"),
    ("Ariane da Silva", "Ariane Lipski"),
    ("Ben Alloway", "Benny Alloway"),
    ("Brad Scott", "Bradley Scott"),
    ("Brianna Fortino", "Brianna Van Buren"),
    ("Robert McDaniel", "Bubba McDaniel"),
    ("Claudia Gadelha", "Caludia Gadelha"),
    ("Claudio Puelles", "Caludio Puelles"),
    ("Carlo Pedersoli Jr.", "Carlo Pedersoli"),
    ("Cheyanne Vlismas", "Cheyanne Buys"),
    ("Constantinos Philippou", "Costas Philippou"),
    ("Cristiane Justino", "Cris Cyborg"),
    ("Da Woon Jung", "Da Un Jung", "Da-Un Jung"),
    ("Batgerel Danaa", "Danaa Batgerel"),
    ("Elizeu Zaleski dos Santos", "Elizeu Dos Santos"),
    ("Emily Kagan", "Emily Peters Kagan"),
    ("Glaico Franca Moreira", "Glaico Franca"),
    ("Grigory Popov", "Grigorii Popov"),
    ("Heather Clark", "Heather Jo Clark"),
    ("Alatengheili", "Heili Alateng"),
    ("Humberto Brown Morrison", "Humberto Brown"),
    ("Isabela de Padua", "Isabela De Pauda"),
    ("Jimmy Crute", "Jim Crute"),
    ("Jim Wallhead", "Jimmy Wallhead"),
    ("Joanne Wood", "Joanne Calderwood"),
    ("Joseph Gigliotti", "Joe Gigliotti"),
    ("Josh Culibao", "Joshua Culibao"),
    ("Josh Sampo", "Joshua Sampo"),
    ("Juan Manuel Puig", "Juan Puig"),
    ("Ramiro Hernandez", "Junior Hernandez"),
    ("Kai Kamaka III", "Kai Kamaka"),
    ("Kai Kara-France", "Kai Kara France"),
    ("Khaos Williams", "Kalinn Williams"),
    ("Katlyn Cerminara", "Katlyn Chookagian"),
    ("Edimilson Souza", "Kevin Souza"),
    ("Krzysztof Jotko", "Krzystof Jotko"),
    ("Leonardo Guimaraes", "Leonardo Augusto Leleco"),
    ("Pingyuan Liu", "Liu Pingyuan"),
    ("Lucie Pudilova", "Luci Pudilova"),
    ("Eduardo Garagorri", "Luiz Garagorri"),
    ("Michelle Waterson-Gomez", "Michelle Waterson"),
    ("Antonio Rodrigo Nogueira", "Minotauro Nogueira"),
    ("Mirko Filipovic", "Mirko Cro Cop"),
    ("Mizuki", "Mizuki Inoue"),
    ("Montserrat Conejo Ruiz", "Montserrat Conejo"),
    ("Montse Rendon", "Montserrat Rendon"),
    ("Liang Na", "Na Liang"),
    ("Nicholas Musoke", "Nico Musoke"),
    ("Nina Nunes", "Nina Ansaroff"),
    ("Guangyou Ning", "Ning Guangyou"),
    ("Ode Osbourne", "Ode Obsourne"),
    ("Omar Morales", "Omar Antonio Morales Ferrer"),
    ("Patricio Pitbull", "Patricio Freire"),
    ("Petr Yan", "Peter Yan"),
    ("Phil Rowe", "Philip Rowe"),
    ("Phil Hawes", "Phillip Hawes"),
    ("Marco Polo Reyes", "Polo Reyes"),
    ("Rafael Cavalcante", "Rafael Feijao"),
    ("Quinton Jackson", "Rampage Jackson"),
    ("Raphael Pessoa", "Raphael Pessoa Nunes"),
    ("Ricky Glenn", "Rick Glenn"),
    ("Robert Whiteford", "Rob Whiteford"),
    ("Robert Sanchez", "Roberto Sanchez"),
    ("Anthony Rocco Martin", "Rocco Martin"),
    ("Rodolfo Rubio Perez", "Rodolfo Rubio"),
    ("Rongzhu", "Rong Zhu"),
    ("Seo Hee Ham", "Seohee Ham"),
    ("Sumudaerji", "Su Mudaerji"),
    ("Tecia Pennington", "Tecia Torres"),
    ("Tiago dos Santos e Silva", "Tiago Trator"),
    ("Zhang Tiequan", "Tiequan Zhang"),
    ("Timothy Johnson", "Tim Johnson"),
    ("Yuta Sasaki", "Ulka Sasaki"),
    ("Vernon Ramos Ho", "Vernon Ramos"),
    ("Veronica Hardy", "Veronica Macedo"),
    ("Vicente Luque", "Vincente Luque"),
    ("Waldo Cortes Acosta", "Waldo Cortes-Acosta"),
    ("Zhang Weili", "Weili Zhang"),
    ("Wendell Oliveira Marques", "Wendell Oliveira"),
    ("William Macario", "William Patolino"),
    ("Wulijiburen", "Wuliji Buren"),
    ("Yana Santos", "Yana Kunitskaya"),
    ("Youssef Zalal", "Youssef Zalel"),
    ("Zach Reese", "Zachary Reese"),
    ("Zhalgas Zhumagulov", "Zhalgas Zhamagulov"),
    ("Azunna Anyanwu", "Zu Anyanwu"),
)
_ALIASES = {normalize_name(name): group for group in _GROUPS for name in group}


def preferred_name(name: str) -> str:
    group = _ALIASES.get(normalize_name(name))
    return group[0] if group else str(name)


def canonical_key(name: str) -> str:
    return normalize_name(preferred_name(name))


def name_variants(name: str) -> tuple[str, ...]:
    """Nombres exactos admitidos para buscar o recuperar cachés antiguos."""
    group = _ALIASES.get(normalize_name(name))
    return group if group else (str(name),)


def same_fighter(left: str, right: str) -> bool:
    return bool(canonical_key(left)) and canonical_key(left) == canonical_key(right)
