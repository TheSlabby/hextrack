'use client';

import Image from "next/image";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ClipLoader } from "react-spinners";
import SearchPlayer from "../../../components/SearchPlayer";
import { motion } from "framer-motion";

export default function SummonerPage({ params }) {
    // const [puuid, setPuuid] = useState();
    const [invalidUser, setInvalidUser] = useState(false);
    const [stats, setStats] = useState<any>();

    const { riotId }: { riotId: string } = use(params);
    const playerName = riotId.replace('-', '#');

    
    useEffect(() => {
        const update = async () => {
            const result = await fetch(`/api/update/${riotId}`);
            if (!result.ok) {
                setInvalidUser(true);
            } else {
                const result = await fetch(`/api/stats/${riotId}`);
                const json = await result.json();
                setStats(json);
            }
        }


        // run update
        console.log('updating user...');
        update();
    }, [riotId]);

    // USER IS INVALID
    if (invalidUser) return (
        <div className="flex flex-col min-h-screen bg-gradient-to-b from-gray-900 to-black text-white p-6 sm:p-12 font-[family-name:var(--font-geist-sans)]">
            <p className="mt-20 mb-5 text-3xl text-red-500 text-center font-bold">
                Invalid user: <span className="font-light">{playerName}</span>
            </p>
            <SearchPlayer />
        </div>
    )


    // LOADING
    if (!stats) return (
        <div className="flex flex-col min-h-screen bg-gradient-to-b from-gray-900 to-black text-white p-6 sm:p-12 font-[family-name:var(--font-geist-sans)]">
            <p className="text-3xl font-light italic text-center my-20">Loading {playerName}...</p>
            <ClipLoader className="mx-auto" color="#36d7b7" size={100} aria-label="Loading Spinner" />
        </div>
    )



    // parse stats
    const soloQueue = stats.rankedInfo.find(info => info.queueType === "RANKED_SOLO_5x5");
    const totalMatches = stats.totalMatches;
    const avgKills = (stats.all.kills / totalMatches).toFixed(2);
    const avgDeaths = (stats.all.deaths / totalMatches).toFixed(2);
    const avgAssists = (stats.all.assists / totalMatches).toFixed(2);
    const puuid = stats.puuid;



    // sort matches by newest first
    const matches = stats.matches.sort((a, b) => {
        return b.data.info.gameEndTimestamp - a.data.info.gameEndTimestamp;
    });

    // LOADED SUCCESSFULLY
    return (
        <div className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white p-6 sm:p-12 font-[family-name:var(--font-geist-sans)]">
            {/* <div className="w-full flex justify-center mb-10 mt-2"><HexTrackLogo /></div> */}
            
            <div className="flex flex-col sm:flex-row justify-between">
                <div className="flex">
                    <Image
                        width={150}
                        height={150}
                        src={stats.iconURL}
                        alt="Profile Icon"
                        className="rounded-3xl object-cover shadow-2xl"
                        priority={true}
                        quality={85}
                    />
                    <div className="ml-10 flex flex-col">
                        <p className="text-3xl font-extrabold">{playerName}</p>
                        <p className="text-lg font-light">{soloQueue?.tier} {soloQueue?.rank}</p>
                        <p className="text-lg font-light">Average KDA: <span className="font-normal">{avgKills}/<span className="text-red-400">{avgDeaths}</span>/{avgAssists}</span></p>
                        <p className="text-sm italic font-light mt-3">{totalMatches} matches found</p>
                    </div>
                </div>
                

                <div className="sm:pl-50 mt-3 md:mt-0">
                    <SearchPlayer />
                </div>
                
            </div>
            
            <p className="mt-10 font-bold text-xl underlin text-center">Match History</p>




            <div className="flex justify-center flex-col gap-3 mt-2 w-full mx-auto md:flex-row md:flex-wrap lg:flex-col lg:flex-wrap">
                {matches.map(match => {
                    const players = match.data.info.participants;
                    const player = players.find(player => player.puuid == puuid)
                    const victory = player.win;
                    const champImage = `https://ddragon.leagueoflegends.com/cdn/15.5.1/img/champion/${player.championName}.png`

                    // get when game was played
                    let gameDate: any = Math.floor((new Date().getTime() - new Date(match.data.info.gameEndTimestamp).getTime()) / (1000 * 60 * 60 * 24));
                    if (gameDate == 0) gameDate = 'Today';
                    else if (gameDate == 1) gameDate = '1 day ago';
                    else if (gameDate > 1) gameDate = `${gameDate} days ago`;

                    // for other players in list
                    const getPlayerDiv = (p) => {
                        const isMe = p.puuid == player.puuid;
                        const champImage = `https://ddragon.leagueoflegends.com/cdn/15.5.1/img/champion/${p.championName}.png`
                        
                        return (
                        <div className="flex">
                            <Image
                                width={20}
                                height={20}
                                src={champImage}
                                alt=""
                                className="object-cover shadow-2xl"
                                priority={true}
                                quality={85}
                            />
                            <Link
                                href={`/summoner/${p.riotIdGameName}-${p.riotIdTagline}`}
                                className={`${!isMe && 'hover:text-cyan-400 hover:underline'} transition duration-200 text-xs ml-1 font-light ${isMe ? 'text-yellow-300' : 'text-white'}`}>
                                    {p.riotIdGameName}
                            </Link>
                        </div>
                        )
                    }

                    return (
                    <motion.div
                        whileHover={{scale: 1.01}} transition={{type: 'spring', stiffness: 300, damping: 10}}
                        className={`flex mx-auto justify-around md:w-200 w-100 p-4 h-30 rounded-3xl shadow-xl bg-gradient-to-br
                        ${victory ? 'from-blue-900 to-blue-950' : 'from-red-900 to-red-950'}`} key={match.matchId}>

                        {/* GENERAL INFO */}
                        <div className="flex flex-col">
                            <p className="text-sm italic text-gray-200 text-center">{gameDate}</p>
                            <Image
                                width={70}
                                height={70}
                                src={champImage}
                                alt="Profile Icon"
                                className="object-cover shadow-2xl"
                                priority={true}
                                quality={85}
                            />
                        </div>


                        {/* GAME INFO */}
                        <div className="flex flex-col">
                            <p className="ml-1 text-md text-white">
                            Damage Done: <span className="font-bold">{player.totalDamageDealtToChampions.toLocaleString()}</span>
                            </p>
                            <p className="ml-1 text-md text-white">
                            KDA: <span className="font-bold">{player.kills}<span className="text-gray-400"> / </span>
                                <span className="text-red-300">{player.deaths}</span>
                                <span className="text-gray-400"> / </span>{player.assists}</span>
                            </p>
                            <p className="ml-1 text-md text-white">
                            CS: <span className="font-bold">{player.totalMinionsKilled + player.neutralMinionsKilled}</span>
                            </p>
                            <p className="ml-1 text-md text-white">
                            Result: <span className="font-bold">{player.win ? "Win" : "Loss"}</span>
                            </p>
                        </div>
                        {/* PLAYERS IN LOBBY */}
                        <div className="hidden sm:flex">
                            <div className="flex flex-col">
                            {players.map(p => {
                                if (p.teamId == 200) return getPlayerDiv(p);
                            })}
                            </div>
                            <div className="flex flex-col ml-2">
                            {players.map(p => {
                                if (p.teamId != 200) return getPlayerDiv(p);
                            })}
                            </div>
                        </div>
                    </motion.div>
                    )
                })}
            </div>

            {/* <p>{JSON.stringify(matches)}</p> */}
        </div>
    )
}