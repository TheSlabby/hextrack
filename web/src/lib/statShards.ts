/**
 * Stat shards (the three small rows under a rune page): id -> label, icon and the rows it can sit in.
 *
 * Match-v5 stores them as `perks.statPerks` {offense, flex, defense}. Data Dragon's
 * `runesReforged.json` doesn't list them, so names and icons follow CommunityDragon's `perks.json`
 * (checked on patch 16.18). Icon file names don't always match the shard: "Health" (+65, 5011)
 * uses the health-scaling art and "Health Scaling" (5001) the health-plus art, as in the client.
 *
 * Since season 2024 the rows are: offense adaptive / attack speed / ability haste, flex adaptive /
 * move speed / health scaling, defense health / tenacity / health scaling. Armor (5002) and magic
 * resist (5003) were the old flex and defense options; they are kept so older games still render.
 */

const CDRAGON_STATMODS =
  "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perk-images/statmods";

/** 0 offense, 1 flex, 2 defense (the API's `ShardPick.row`). */
export type ShardRow = 0 | 1 | 2;

export interface StatShard {
  id: number;
  name: string;
  /** What it gives, e.g. "+10% attack speed". */
  effect: string;
  /** Absolute icon URL (CommunityDragon). */
  icon: string;
  /** Two-letter fallback when the icon can't load. */
  glyph: string;
}

function shard(id: number, name: string, effect: string, file: string, glyph: string): StatShard {
  return { id, name, effect, icon: `${CDRAGON_STATMODS}/${file}.png`, glyph };
}

export const STAT_SHARDS: Readonly<Record<number, StatShard>> = {
  5001: shard(5001, "Health Scaling", "+10–180 health (based on level)", "statmodshealthplusicon", "HP"),
  5002: shard(5002, "Armor", "+6 armor", "statmodsarmoricon", "AR"),
  5003: shard(5003, "Magic Resist", "+8 magic resist", "statmodsmagicresicon", "MR"),
  5005: shard(5005, "Attack Speed", "+10% attack speed", "statmodsattackspeedicon", "AS"),
  5007: shard(5007, "Ability Haste", "+8 ability haste", "statmodscdrscalingicon", "AH"),
  5008: shard(5008, "Adaptive Force", "+9 adaptive force", "statmodsadaptiveforceicon", "AF"),
  5010: shard(5010, "Move Speed", "+2.5% move speed", "statmodsmovementspeedicon", "MS"),
  5011: shard(5011, "Health", "+65 health", "statmodshealthscalingicon", "HP"),
  5012: shard(5012, "Resist Scaling", "+1–8 armor and magic resist (based on level)", "statmodsadaptiveforcescalingicon", "RS"),
  5013: shard(5013, "Tenacity and Slow Resist", "+15% tenacity and slow resist", "statmodstenacityicon", "TN"),
};

export const SHARD_ROW_LABELS: Readonly<Record<ShardRow, string>> = {
  0: "Offense",
  1: "Flex",
  2: "Defense",
};

/** The current options in each row, in the client's left-to-right order. */
export const SHARD_ROW_OPTIONS: Readonly<Record<ShardRow, readonly number[]>> = {
  0: [5008, 5005, 5007],
  1: [5008, 5010, 5001],
  2: [5011, 5013, 5001],
};

export const SHARD_ROWS: readonly ShardRow[] = [0, 1, 2];

/** Any shard id -> its info; unknown ids get a generic entry instead of undefined. */
export function statShard(id: number): StatShard {
  return STAT_SHARDS[id] ?? { id, name: `Stat shard ${id}`, effect: "", icon: "", glyph: "?" };
}

/**
 * The options to draw in a row: the current three, then any other id games actually took there
 * (older patches' armor / magic resist), so a picked shard is never missing from the row.
 */
export function shardRowOptions(row: ShardRow, seen: Iterable<number> = []): number[] {
  const ids = [...SHARD_ROW_OPTIONS[row]];
  for (const id of seen) if (!ids.includes(id)) ids.push(id);
  return ids;
}
