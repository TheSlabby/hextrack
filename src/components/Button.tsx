'use client';

import { motion } from "framer-motion";

const buttonVariants = {
    hover: {
        scale: 1.02,
        boxShadow: '0px 4px 15px rgba(0, 0, 0, 0.1)', // Add a shadow
        transition: {
            duration: 0.3,
            ease: 'easeInOut',
        }
    },
    tap: {
        scale: 0.97,
        transition: {
            duration: 0.2
        }
    }
}

export default function Button({ children, className = '', ...props}) {
    return (
        <motion.button
            variants={buttonVariants}
            whileHover="hover"
            whileTap="tap"
            className={`px-4 cursor-pointer py-2 rounded-2xl outline-1 outline-black shadow-xl text-white font-bold focus:ring-2 ${className}`}
            {...props}
        >
            {children}
        </motion.button>
    )
}