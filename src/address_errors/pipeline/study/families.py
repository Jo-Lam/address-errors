"""Hand-written family names for the data clusters (written after reading
the clusters; never fed back into clustering)."""

FAMILIES = {
    "F01 locality/town/county house style": ["C01", "C06", "C07", "C08", "C26", "C60", "C77"],
    "F02 unit word added on a bare unit id": ["C04"],
    "F03 sub-unit text deleted (unit word, or whole numberless sub-unit)": ["C03"],
    "F04 name or unit text added before the house number": ["C02"],
    "F05 sub-unit invented on a building-level UPRN": ["C23", "C51", "C56", "C32"],
    "F06 floor/position descriptor or 'AT' connective inserted": ["C05", "C20", "C34", "C53", "C31"],
    "F07 unit-type word swapped (FLAT/APARTMENT/ROOM)": ["C14", "C44"],
    "F08 building name dropped or shortened": ["C09", "C49"],
    "F09 building name added elsewhere in the string": ["C33", "C37", "C38", "C29"],
    "F10 name/street partly replaced": ["C10", "C27", "C57", "C35"],
    "F11 components reordered": ["C13", "C47", "C58", "C65", "C48", "C82", "C83", "C78"],
    "F12 street deleted or extra street text inserted (incl. 'OFF <road>')": ["C15", "C11", "C45"],
    "F13 word abbreviated or expanded (any component)": ["C12", "C18", "C67"],
    "F14 word spacing or hyphenation (any component)": ["C19", "C30", "C63", "C72"],
    "F15 1-2 character typo (any component)": ["C46", "C50"],
    "F16 range separator or punctuation only (60/62 vs 60-62)": ["C21"],
    "F17 range <-> single number": ["C43", "C39", "C24", "C75"],
    "F18 number letter-suffix dropped/added/swapped": ["C22", "C36", "C70"],
    "F19 number slip to a nearby number (+-1, +-2)": ["C52", "C55", "C62", "C66"],
    "F20 number keyed differently (digit change/drop, other)": ["C54", "C42", "C64", "C73"],
    "F21 house number dropped": ["C16"],
    "F22 sub-unit number or room span dropped": ["C25", "C17"],
    "F23 unit id re-encoded to a building scheme (block/floor/room codes)": ["C28", "C40", "C59", "C61", "C68", "C69", "C71", "C74", "C79", "C80", "C81"],
    "F24 organisation name dropped/added": ["C41", "C76"],
}
