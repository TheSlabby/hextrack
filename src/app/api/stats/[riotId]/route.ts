import { PrismaClient } from "@prisma/client";
import { TURBOPACK_CLIENT_MIDDLEWARE_MANIFEST } from "next/dist/shared/lib/constants";
import { NextResponse } from "next/server";

const prisma = new PrismaClient();
const riot_api_key = process.env.RIOT_KEY;

export async function GET(request, { params }): Promise<NextResponse> {
    let { riotId }: { riotId: string } = await params;
    riotId = riotId.replace('-', '#');
    var puuid;

    const result = await prisma.riotAccount.findUnique({
        where: {
            riotId: riotId
        }
    });

    if (result) {
        // const resultJson = await result.json();
        puuid = result.puuid;
        console.log("already have puuid in database:");
    } else {
        return NextResponse.json('user not in database rip', {status: 400});
    }

    console.log("USING PUUID:", puuid);


    // DATA OF USER
    let totalKills = 0;
    let totalDeaths = 0;
    let totalAssists = 0;
    let totalMatches = 0;

    const matches = await prisma.matches.findMany();
    for (const match of matches) {
        const matchData = match.data;
        const participant = matchData.info.participants.find(p => p.puuid == puuid);
        if (participant) {
            totalKills += participant.kills;
            totalDeaths += participant.deaths;
            totalAssists += participant.assists;
            totalMatches++;
            console.log('all participant data:', participant);
        }
    }
    const kda = (totalKills + totalAssists) / totalDeaths;


    return NextResponse.json({
        puuid,
        totalMatches: totalMatches,
        all: {
            kills: totalKills,
            deaths: totalDeaths,
            assists: totalAssists
        },
        kda: kda.toFixed(2),
    }, {
        status: 200
    });
    
}