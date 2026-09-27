set pagination off
set confirm off
set print elements 0
watch *(int*)0x109CBEC
continue
printf "\n===HIT1===\n"
printf "PC="
x/i $pc
info registers eax ebx ecx edx esi edi ebp
printf "SRC esi-0x60:\n"
x/48xw $esi-0x60
printf "DST edi-0x20:\n"
x/16xw $edi-0x20
continue
printf "\n===HIT2===\n"
printf "PC="
x/i $pc
info registers eax ebx ecx edx esi edi ebp
printf "SRC esi-0x60:\n"
x/48xw $esi-0x60
continue
printf "\n===HIT3===\n"
printf "PC="
x/i $pc
info registers eax ebx ecx edx esi edi ebp
printf "SRC esi-0x60:\n"
x/48xw $esi-0x60
detach
quit
