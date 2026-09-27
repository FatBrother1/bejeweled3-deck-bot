set pagination off
set confirm off
watch *(int*)0x109CBEC
continue
printf "\n===HIT1===\n"
bt 8
x/2i $pc
continue
printf "\n===HIT2===\n"
bt 8
x/2i $pc
continue
printf "\n===HIT3===\n"
bt 8
x/2i $pc
continue
printf "\n===HIT4===\n"
bt 8
x/2i $pc
detach
quit
