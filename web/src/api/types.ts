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

// squad (duo synergy grid, who carries whom)
export type SquadPairs = Schemas["SquadPairs"];
export type SquadPair = Schemas["SquadPair"];
export type SquadPlayer = Schemas["SquadPlayer"];
// stacks (games the squad played together)
export type StackSummary = Schemas["StackSummary"];
export type StackGame = Schemas["StackGame"];
export type StackGamePage = Schemas["StackGamePage"];
export type StackPlayer = Schemas["StackPlayer"];
export type StackLineup = Schemas["StackLineup"];
export type StackAward = Schemas["StackAward"];
export type StackHighlight = Schemas["StackHighlight"];
export type StackVerdict = Schemas["StackVerdict"];
export type VerdictTier = StackVerdict["tier"];
export type StackQueue = StackSummary["queue"];
export type StackSize = 3 | 4 | 5;
// personal insights (Trends tab)
export type SessionInsights = Schemas["SessionInsights"];
export type SessionGameBucket = Schemas["SessionGameBucket"];
export type SessionStateBucket = Schemas["SessionStateBucket"];
export type ScheduleInsights = Schemas["ScheduleInsights"];
export type ScheduleCell = Schemas["ScheduleCell"];
export type ScheduleDay = Schemas["ScheduleDay"];
export type ScheduleHour = Schemas["ScheduleHour"];
export type ScheduleWindow = Schemas["ScheduleWindow"];
export type MatchupInsights = Schemas["MatchupInsights"];
export type ChampionMatchup = Schemas["ChampionMatchup"];
export type LuckInsights = Schemas["LuckInsights"];
export type LuckGame = Schemas["LuckGame"];
// records
export type Records = Schemas["Records"];
export type RecordCategory = Schemas["RecordCategory"];
export type RecordEntry = Schemas["RecordEntry"];
export type QuadrakillCount = Schemas["QuadrakillCount"];

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
/** "season" (since settings.season_start) or "all" stored games. */
export type StatsSince = SquadPairs["since"];
export type SessionState = SessionStateBucket["state"];
export type RecordKey = RecordCategory["key"];
export type RecordUnit = RecordCategory["unit"];
export type RecordScope = Records["scope"];

// --- request parameters --------------------------------------------------------------

export type MatchListQuery = NonNullable<operations["list_summoner_matches"]["parameters"]["query"]>;
export type SearchQuery = operations["search_summoners"]["parameters"]["query"];
export type AiTrendQuery = NonNullable<operations["get_ai_trend"]["parameters"]["query"]>;
export type AiExplainQuery = NonNullable<operations["get_ai_explain"]["parameters"]["query"]>;
export type SquadPairsQuery = NonNullable<operations["get_squad_pairs"]["parameters"]["query"]>;
export type SessionInsightsQuery = NonNullable<operations["get_session_insights"]["parameters"]["query"]>;
export type ScheduleInsightsQuery = NonNullable<operations["get_schedule_insights"]["parameters"]["query"]>;
export type MatchupInsightsQuery = NonNullable<operations["get_matchup_insights"]["parameters"]["query"]>;
export type LuckInsightsQuery = NonNullable<operations["get_luck_insights"]["parameters"]["query"]>;
export type RecordsQuery = NonNullable<operations["get_records"]["parameters"]["query"]>;

/** A Riot ID pair as used in URLs and API paths. */
export interface RiotIdParts {
  gameName: string;
  tagLine: string;
}
