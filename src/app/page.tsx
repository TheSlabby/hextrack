'use client';

import { useRouter } from "next/navigation";
import Button from "../components/Button"
import { useState } from "react";

export default function Home() {
  const router = useRouter();
  const [searchId, setSearchId] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

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


      <div className="w-xl mt-30 mx-auto flex flex-col align-center">
        <p className="text-lg text-center">Search for a Player</p>
        <input value={searchId} onChange={e => setSearchId(e.target.value)} className="mt-3 w-3/4 mx-auto placeholder:text-slate-500 text-slate-200 border border-slate-200 rounded-lg px-3 py-2 transition duration-300 ease focus:outline-none focus:border-slate-400 hover:border-slate-300 shadow-sm focus:shadow" placeholder="TheSlab#333" />
        <Button className="bg-blue-800 w-1/4 mx-auto mt-3" onClick={searchPlayer}>
          Search
        </Button>
        <p className="text-red-300 italic text-center mt-2">
          {errorMessage}
        </p>
      </div>

    </div>
  );
}
