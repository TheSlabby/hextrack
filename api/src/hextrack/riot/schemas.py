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
