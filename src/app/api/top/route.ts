import { PrismaClient } from "@prisma/client";
import { NextResponse } from "next/server";

const prisma = new PrismaClient();

export async function GET(request): Promise<NextResponse> {
    const matches = await prisma.matches.findMany({take: 500});
    const users = await prisma.riotAccount.findMany({take: 500}); 

    const participantData = {}

    for (const user of users) {
        participantData[user.puuid] = {
            name: user.riotId,
            puuid: user.puuid,
            kills: 0,
            deaths: 0,
            assists: 0,
            wins: 0,
            losses: 0,
            totalMatches: 0,
            topKills: 0,
            damageDealt: 0,
            damageTaken: 0,
            totalCS: 0,
            playedWith: {},
            iconURL: user.profileIconURL,
        };
    }

    for (const match of matches as any) {
        const participants = match.data?.info?.participants;
        for (const participant of participants) {
            const puuid = participant.puuid;

            if (puuid in participantData) {
                // check for our best friends
                for (const p of participants) {
                    if (p.puuid !== puuid)
                        participantData[puuid].playedWith[p.riotIdGameName] = participantData[puuid].playedWith[p.riotIdGameName] ? participantData[puuid].playedWith[p.riotIdGameName] + 1 : 1;
                }

                // track this user data
                participantData[puuid].totalMatches += 1;
                participantData[puuid].kills += participant.kills;
                participantData[puuid].deaths += participant.deaths;
                participantData[puuid].assists += participant.assists;
                participantData[puuid].damageDealt += participant.totalDamageDealt;
                participantData[puuid].totalCS += participant.totalMinionsKilled + participant.neutralMinionsKilled;
                // console.log(participant);
                participantData[puuid].damageTaken += participant.totalDamageTaken;
                if (participant.win)
                    participantData[puuid].wins += 1
                else
                    participantData[puuid].losses += 1

                if (participant.kills > participantData[puuid].topKills)
                    participantData[puuid].topKills = participant.kills;

            }
        }
    }

    // now get averages
    for (const participant of Object.values(participantData) as any) {
        participant.kda = participant.deaths > 0 ? ((participant.kills + participant.assists) / participant.deaths).toFixed(2) : participant.kills + participant.assists;
        participant.winrate = participant.losses > 0 ? participant.wins / (participant.wins + participant.losses) : 1;    
        // get best friend with beautiful javascript reduce
        participant.bestFriend = Object.entries(participant.playedWith).reduce(
            (best, current) => {
                const [bestPuuid, bestCount] = best;
                const [currPuuid, currCount] = current;
                return currCount > bestCount ? [currPuuid, currCount] : best;
            }
        ); 
        delete participantData[participant.puuid].playedWith;
    }


    // now return sorted array
    const sortedArray = Object.values(participantData).sort((a: any, b: any) => b.kda - a.kda);

    // console.log(sortedArray);
    return NextResponse.json(sortedArray);
}