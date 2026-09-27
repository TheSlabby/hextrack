/** Champion display names from match-v5 / Data Dragon keys. */

/** Keys whose display name is not a plain camel-case split (both key spellings in use). */
const CHAMPION_NAMES: Readonly<Record<string, string>> = {
  AurelionSol: "Aurelion Sol",
  BelVeth: "Bel'Veth",
  Belveth: "Bel'Veth",
  ChoGath: "Cho'Gath",
  Chogath: "Cho'Gath",
  DrMundo: "Dr. Mundo",
  FiddleSticks: "Fiddlesticks",
  Fiddlesticks: "Fiddlesticks",
  JarvanIV: "Jarvan IV",
  KSante: "K'Sante",
  KaiSa: "Kai'Sa",
  Kaisa: "Kai'Sa",
  KhaZix: "Kha'Zix",
  Khazix: "Kha'Zix",
  KogMaw: "Kog'Maw",
  LeBlanc: "LeBlanc",
  Leblanc: "LeBlanc",
  MonkeyKing: "Wukong",
  Nunu: "Nunu & Willump",
  RekSai: "Rek'Sai",
  Renata: "Renata Glasc",
  VelKoz: "Vel'Koz",
  Velkoz: "Vel'Koz",
};

/** "MonkeyKing" -> "Wukong", "MissFortune" -> "Miss Fortune", "Kaisa" -> "Kai'Sa". */
export function championDisplayName(key: string): string {
  return CHAMPION_NAMES[key] ?? key.replace(/([a-z])([A-Z])/g, "$1 $2");
}

/** URL segment of a champion page: the Data Dragon key in lower case ("monkeyking"). */
export function championSlug(key: string): string {
  return key.toLowerCase();
}

/** "Patches 16.18 + 16.17", "Patch 16.18", "Whole season". */
export function patchWindowLabel(
  value: string,
  recent: readonly string[] = [],
): string {
  if (value === "season") return "Whole season";
  if (value === "recent")
    return recent.length > 1
      ? `Patches ${recent.join(" + ")}`
      : recent[0]
        ? `Patch ${recent[0]}`
        : "Recent patches";
  return `Patch ${value}`;
}
