'use client';

import { useRouter } from "next/navigation";
import Button from "../components/Button"
import { useEffect, useState } from "react";
import { ClipLoader } from "react-spinners";
import Image from "next/image";
import { motion } from "framer-motion";

export default function Home() {
  const router = useRouter();
  const [searchId, setSearchId] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [topData, setTopData] = useState<any>();


  useEffect(() => {
    const updateTop = async () => {
      const result = await fetch('/api/top');
      const data = await result.json();
      setTopData(data);
    }

    updateTop();
  }, []);


  const searchPlayer = () => {
    const splitId = searchId.split('#');
    const formatted = searchId.replace('#', '-');
    if (splitId.length == 2) {
      router.push('/summoner/' + formatted)
    } else {
      setErrorMessage('Invalid search format (example: TheSlab#333)');
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white p-6 sm:p-12 font-[family-name:var(--font-geist-sans)]">
      <p className="text-7xl pt-30 text-center text-white font-extrabold">HexTrack</p>
      <p className="text-center text-xl mt-5 font-extralight text-gray-200">League of Legends Stat Tracker</p>


      <div className="max-w-3xl mt-30 mx-auto flex flex-col align-center">
        <p className="text-lg text-center">Search for a Player</p>
        <input value={searchId} onChange={e => setSearchId(e.target.value)} className="mt-3 w-3/4 mx-auto placeholder:text-slate-500 text-slate-200 border border-slate-200 rounded-lg px-3 py-2 transition duration-300 ease focus:outline-none focus:border-slate-400 hover:border-slate-300 shadow-sm focus:shadow" placeholder="TheSlab#333" />
        <Button className="bg-blue-800 w-1/4 mx-auto mt-3" onClick={searchPlayer}>
          Search
        </Button>
        <p className="text-red-300 italic text-center mt-2">
          {errorMessage}
        </p>
      </div>

      
      {topData ? (
        <div className="mt-20 flex flex-col gap-3">
          <p className="font-bold text-center text-3xl text-violet-100">Leaderboard</p>
          {topData.map(p => (
            <motion.div key={p.puuid} onClick={() => {
              router.push(`/summoner/${p.name.replace('#', '-')}`)
            }} whileHover={{scale: 1.02}} transition={{type: 'spring', stiffness: 300, damping: 10}}
            className="cursor-pointer flex justify-between w-full sm:w-125 mx-auto bg-gradient-to-r rounded-xl p-2 px-5 shadow-xl bg-purple-900 to-violet-950">

              {/* NAME AND ICON */}
              <div className="flex flex-col justify-center">
                <Image
                    width={75}
                    height={75}
                    src={p.iconURL}
                    alt="Profile Icon"
                    className="rounded-3xl object-cover shadow-2xl"
                    priority={true}
                    quality={85}
                />
                <p className="font-normal text-sm mt-1 text-center">
                  {p.name}
                </p>
                <p className="font-light text-xs text-gray-400 italic text-center">
                  {p.totalMatches} games found
                </p>
              </div>

              {/* STATS */}
              <div className="flex flex-col justify-center text-sm">
                
                <p className="">K/DA: <span className="text-amber-200 font-bold">{p.kda}</span></p>
                <p className="">Total KDA: <span className="font-bold">{p.kills}</span>
                  <span className="font-gray-400"> / </span><span className="font-bold text-red-400">{p.deaths}</span>
                  <span className="font-gray-400"> / </span><span className="font-bold">{p.assists}</span>
                </p>
                <p className="">Total Damage Dealt: <span className="font-bold text-green-200">{p.damageDealt.toLocaleString()}</span></p>
                <p className="">Total Damage Taken: <span className="font-bold text-red-200">{p.damageTaken.toLocaleString()}</span></p>
                <p className="">Win Rate: <span className="font-bold">{Math.round(p.winrate * 100)}%</span></p>
              </div>

            </motion.div>
          ))}
        </div>
      ):(
            <div className="mt-20 flex">
              <ClipLoader className="mx-auto" color="#36d7b7" size={50} aria-label="Loading Spinner" />
          </div>
      )}

    </div>
  );
}
