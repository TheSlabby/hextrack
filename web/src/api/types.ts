/**
 * Friendly aliases for every API schema (generated types live in ./schema.d.ts).
 * Import from "@/api/types" in components; never hand-write response shapes.
 */
import type { components, operations } from "./schema";

type Schemas = components["schemas"];

export type AiExplain = Schemas["AiExplain"];
export type AiTrend = Schemas["AiTrend"];
export type AiTrendPoint = Schemas["AiTrendPoint"];
export type BestAlly = Schemas["BestAlly"];
export type ChampionStat = Schemas["ChampionStat"];
export type ErrorResponse = Schemas["ErrorResponse"];
export type FeatureAttribution = Schemas["FeatureAttribution"];
export type HTTPValidationError = Schemas["HTTPValidationError"];
export type Health = Schemas["Health"];
export type HealthModel = Schemas["HealthModel"];
export type HealthPoller = Schemas["HealthPoller"];
export type HealthRiot = Schemas["HealthRiot"];
export type Leaderboard = Schemas["Leaderboard"];
export type LeaderboardEntry = Schemas["LeaderboardEntry"];
export type MatchDetail = Schemas["MatchDetail"];
export type MatchPage = Schemas["MatchPage"];
export type MatchSummary = Schemas["MatchSummary"];
export type Meta = Schemas["Meta"];
export type ObjectiveStat = Schemas["ObjectiveStat"];
export type ParticipantSummary = Schemas["ParticipantSummary"];
export type ProfileStats = Schemas["ProfileStats"];
export type RankEntry = Schemas["RankEntry"];
export type RankHistory = Schemas["RankHistory"];
export type RankPoint = Schemas["RankPoint"];
export type RefreshResult = Schemas["RefreshResult"];
export type RoleStat = Schemas["RoleStat"];
export type RosterEntry = Schemas["RosterEntry"];
export type SummonerProfile = Schemas["SummonerProfile"];
export type SummonerSearchResult = Schemas["SummonerSearchResult"];
export type TeamDetail = Schemas["TeamDetail"];
export type TeamObjectives = Schemas["TeamObjectives"];
export type TeamSummary = Schemas["TeamSummary"];
export type ValidationError = Schemas["ValidationError"];

// --- enums (derived from the schemas so they stay in sync) ---------------------------

export type QueueType = RankEntry["queue_type"];
export type Tier = RankEntry["tier"];
export type Division = NonNullable<RankEntry["rank"]>;
export type Position = ParticipantSummary["team_position"];
export type TeamId = ParticipantSummary["team_id"];
export type FeatureGroup = FeatureAttribution["group"];
export type LeaderboardQueue = Leaderboard["queue"];
export type RefreshStatus = RefreshResult["status"];
export type HealthStatus = Health["status"];

// --- request parameters --------------------------------------------------------------

export type MatchListQuery = NonNullable<operations["list_summoner_matches"]["parameters"]["query"]>;
export type SearchQuery = operations["search_summoners"]["parameters"]["query"];
export type AiTrendQuery = NonNullable<operations["get_ai_trend"]["parameters"]["query"]>;
export type AiExplainQuery = NonNullable<operations["get_ai_explain"]["parameters"]["query"]>;

/** A Riot ID pair as used in URLs and API paths. */
export interface RiotIdParts {
  gameName: string;
  tagLine: string;
}
