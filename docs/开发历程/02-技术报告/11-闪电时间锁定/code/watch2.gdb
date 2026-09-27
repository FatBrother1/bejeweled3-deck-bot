set pagination off
set confirm off
watch *(int*)0x109CBEC
continue
printf "\n===HIT1===\n"
info registers eax ebx ecx edx esi edi
printf "SRC esi:\n"
x/8xw $esi
printf "DST edi:\n"
x/8xw $edi
continue
printf "\n===HIT2===\n"
info registers eax ebx ecx edx esi edi
printf "SRC esi:\n"
x/8xw $esi
printf "DST edi:\n"
x/8xw $edi
continue
printf "\n===HIT3===\n"
info registers eax ebx ecx edx esi edi
printf "SRC esi:\n"
x/8xw $esi
printf "DST edi:\n"
x/8xw $edi
continue
printf "\n===HIT4===\n"
info registers eax ebx ecx edx esi edi
printf "SRC esi:\n"
x/8xw $esi
printf "DST edi:\n"
x/8xw $edi
detach
quit
