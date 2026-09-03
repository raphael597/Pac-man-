import sys
import random
import pygame
from Pacman import Direction, Field, Pacman
from PacmanRenderer import Renderer
from TRex import TRex
from ClaudeEndboss import ClaudeEndboss          # <- dazu

FPS = 25    # Simulationsschritte pro Sekunde

def main():
    pacmans = [[Pacman, "Pacman1"],[Pacman, "Pacman2"],[Pacman, "Pacman3"], [TRex, "Trex1"], [TRex, "Trex2"],
               [ClaudeEndboss, "ClaudeEndboss"]]                      # <- dazu
    walls = [[[5, 3],Direction.east,8], [[5, 4],Direction.south,3], [[12, 4],Direction.south,3],
             [[2,12],Direction.east,8], [[2,11],Direction.north,3], [[ 9,11],Direction.north,3]]
    field = Field(15,pacmans,walls)
    
    pygame.init()
    renderer = Renderer(field)
    clock = pygame.time.Clock()

    running = True
    nr_alive = len(field.pacmans)
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
        if nr_alive > 1:
            nr_alive = 0
            for pacman in random.sample(field.pacmans,len(field.pacmans)):
                if pacman.alive:
                    pacman.TurnOrMoveOrStill()
                    nr_alive += 1

        renderer.draw_field()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


main()