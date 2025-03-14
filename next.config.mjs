/** @type {import('next').NextConfig} */
const nextConfig = {
    images: {
        remotePatterns: [
            {
                protocol: 'https',
                hostname: 'static.bigbrain.gg',
                pathname: '/assets/lol/riot_static/**'
            },
            {
                protocol: 'https',
                hostname: 'ddragon.leagueoflegends.com',
                pathname: '/cdn/**'
            }
        ]
    }
};

export default nextConfig;
