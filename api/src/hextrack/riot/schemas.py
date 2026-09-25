"""Pydantic DTOs for the Riot endpoints we read. Only consumed fields are declared;
``extra="allow"`` keeps everything else so payloads round-trip losslessly."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RiotDto(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class AccountDto(RiotDto):
    """account-v1 /riot/account/v1/accounts/..."""

    puuid: str = Field(min_length=1)
    game_name: str | None = Field(default=None, alias="gameName")
    tag_line: str | None = Field(default=None, alias="tagLine")


class SummonerDto(RiotDto):
    """summoner-v4 /lol/summoner/v4/summoners/by-puuid/{puuid}."""

    puuid: str = Field(min_length=1)
    profile_icon_id: int = Field(alias="profileIconId")
    summoner_level: int = Field(alias="summonerLevel")
    revision_date: int | None = Field(default=None, alias="revisionDate")


class LeagueEntryDto(RiotDto):
    """league-v4 /lol/league/v4/entries/by-puuid/{puuid} element."""

    queue_type: str = Field(alias="queueType")
    tier: str
    #: "I".."IV"; Riot sends "I" for apex tiers, callers treat it as None there.
    rank: str | None = None
    league_points: int = Field(alias="leaguePoints")
    wins: int
    losses: int
    puuid: str | None = None
    league_id: str | None = Field(default=None, alias="leagueId")
    hot_streak: bool = Field(default=False, alias="hotStreak")
    veteran: bool = False
    fresh_blood: bool = Field(default=False, alias="freshBlood")
    inactive: bool = False


class ParticipantDto(RiotDto):
    """match-v5 info.participants[] (fields validated before storage)."""

    puuid: str = Field(min_length=1)
    participant_id: int = Field(alias="participantId")
    team_id: int = Field(alias="teamId")
    champion_id: int = Field(alias="championId")
    champion_name: str = Field(alias="championName")
    win: bool
    kills: int
    deaths: int
    assists: int
    riot_id_game_name: str | None = Field(default=None, alias="riotIdGameName")
    riot_id_tagline: str | None = Field(default=None, alias="riotIdTagline")
    summoner_name: str | None = Field(default=None, alias="summonerName")
    team_position: str | None = Field(default=None, alias="teamPosition")


class MatchMetadataDto(RiotDto):
    match_id: str = Field(alias="matchId", min_length=1)
    data_version: str | None = Field(default=None, alias="dataVersion")
    participants: list[str] = Field(default_factory=list)


class TeamDto(RiotDto):
    team_id: int = Field(alias="teamId")
    win: bool


class MatchInfoDto(RiotDto):
    game_mode: str = Field(alias="gameMode")
    game_version: str = Field(alias="gameVersion")
    game_duration: int = Field(alias="gameDuration")
    game_start_timestamp: int = Field(alias="gameStartTimestamp")
    queue_id: int = Field(alias="queueId")
    platform_id: str | None = Field(default=None, alias="platformId")
    game_type: str | None = Field(default=None, alias="gameType")
    end_of_game_result: str | None = Field(default=None, alias="endOfGameResult")
    participants: list[ParticipantDto]
    teams: list[TeamDto] = Field(default_factory=list)


class MatchDto(RiotDto):
    """match-v5 /lol/match/v5/matches/{matchId}."""

    metadata: MatchMetadataDto
    info: MatchInfoDto


class CurrentGamePerksDto(RiotDto):
    perk_ids: list[int] = Field(default_factory=list, alias="perkIds")
    perk_style: int | None = Field(default=None, alias="perkStyle")
    perk_sub_style: int | None = Field(default=None, alias="perkSubStyle")


class CurrentGameParticipantDto(RiotDto):
    """spectator-v5 participants[] (a bot has no puuid)."""

    puuid: str | None = None
    team_id: int = Field(alias="teamId")
    champion_id: int = Field(alias="championId")
    spell1_id: int = Field(default=0, alias="spell1Id")
    spell2_id: int = Field(default=0, alias="spell2Id")
    #: "GameName#TAG"; absent for bots and some anonymised queues.
    riot_id: str | None = Field(default=None, alias="riotId")
    profile_icon_id: int | None = Field(default=None, alias="profileIconId")
    bot: bool = False
    perks: CurrentGamePerksDto | None = None


class BannedChampionDto(RiotDto):
    champion_id: int = Field(alias="championId")
    team_id: int = Field(alias="teamId")
    pick_turn: int = Field(default=0, alias="pickTurn")


class CurrentGameInfoDto(RiotDto):
    """spectator-v5 /lol/spectator/v5/active-games/by-summoner/{puuid}."""

    game_id: int = Field(alias="gameId")
    game_type: str | None = Field(default=None, alias="gameType")
    #: Epoch milliseconds; 0 while the game is still loading.
    game_start_time: int = Field(default=0, alias="gameStartTime")
    map_id: int | None = Field(default=None, alias="mapId")
    #: Seconds since the game started (as of Riot's last update).
    game_length: int = Field(default=0, alias="gameLength")
    platform_id: str | None = Field(default=None, alias="platformId")
    game_mode: str | None = Field(default=None, alias="gameMode")
    game_queue_config_id: int | None = Field(default=None, alias="gameQueueConfigId")
    banned_champions: list[BannedChampionDto] = Field(default_factory=list, alias="bannedChampions")
    participants: list[CurrentGameParticipantDto] = Field(min_length=1)
